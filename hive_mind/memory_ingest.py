"""Hive Mind — Memory Ingestion (v2)

Fire-and-forget pipeline that runs after every agent conversation:
  1. Sends transcript to Gemini Flash for fact extraction
  2. Scores each memory by importance (0-1)
  3. Generates 768-dim embeddings via gemini-embedding-001
  4. Deduplicates at 0.85 cosine similarity
  5. Inserts non-duplicate memories into the DB
  6. Triggers Telegram notification for importance >= 0.8
"""

import json
import logging
import os
import threading
from typing import Optional

from google import genai
from google.genai import types as genai_types

from hive_mind.db import HiveMindDB
from hive_mind.embeddings import (
    decode_embedding,
    encode_embedding,
    find_duplicates,
    generate_embedding,
)

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a memory extraction engine for an AI operating system.

Analyze the conversation below and extract discrete facts worth remembering long-term.

Return ONLY valid JSON:
{{
  "memories": [
    {{
      "summary": "concise one-sentence fact worth keeping",
      "entities": ["person, place, or thing mentioned"],
      "topics": ["category or theme"],
      "importance": 0.0
    }}
  ]
}}

Importance scale:
- 0.9-1.0: Critical facts (user identity, key decisions, core preferences)
- 0.7-0.8: Important context (project details, recurring preferences, goals)
- 0.5-0.6: Useful context (one-off details, specific requests)
- Below 0.5: Not worth keeping — omit these

Rules:
- Only include importance >= 0.5
- Never include API keys, tokens, passwords, or PII
- Summaries must be self-contained (readable without the conversation)
- If nothing is worth keeping, return {{"memories": []}}

Conversation:
{conversation}
"""


def _get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


def _notify_high_importance(memory_id: str, summary: str) -> None:
    """Send Telegram notification for high-importance memories."""
    try:
        import asyncio
        import os
        from telegram import Bot
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
        if not token or not chat_ids:
            return
        chat_id = chat_ids.split(",")[0].strip()

        async def _send():
            bot = Bot(token=token)
            await bot.send_message(
                chat_id=chat_id,
                text=f"🧠 *High-importance memory stored*\n\n`{summary}`\n\nID: `{memory_id}`",
                parse_mode="Markdown",
            )

        asyncio.run(_send())
    except Exception as e:
        logger.warning(f"High-importance notification failed: {e}")


def _run_ingest(
    messages: list[dict],
    agent_id: Optional[str],
    chat_id: Optional[str],
) -> dict:
    """Internal: run the full ingestion pipeline synchronously."""
    hive = HiveMindDB()
    client = _get_gemini_client()

    # Format conversation for Gemini
    conversation = "\n".join(
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
        for m in messages
    )

    # Extract memories via Gemini Flash
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=EXTRACTION_PROMPT.format(conversation=conversation),
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        extracted = json.loads(response.text.strip())
        candidates = extracted.get("memories", [])
    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")
        return {"stored": 0, "error": str(e)}

    if not candidates:
        return {"stored": 0}

    # Load existing embeddings for duplicate detection
    existing_raw = hive.get_all_embeddings(agent_id=agent_id)
    existing = [(mid, decode_embedding(emb)) for mid, emb in existing_raw]

    stored = 0
    high_importance = []

    for candidate in candidates:
        importance = float(candidate.get("importance", 0.5))
        summary = candidate.get("summary", "").strip()
        if not summary or importance < 0.5:
            continue

        # Generate embedding
        try:
            embedding_vec = generate_embedding(summary)
            embedding_hex = encode_embedding(embedding_vec)
        except Exception as e:
            logger.warning(f"Embedding generation failed for memory: {e}")
            embedding_vec = None
            embedding_hex = None

        # Duplicate detection
        if embedding_vec and existing:
            dupes = find_duplicates(embedding_vec, existing)
            if dupes:
                logger.debug(f"Skipping duplicate memory: {summary[:60]}")
                continue

        # Insert memory
        mem_id = hive.insert_memory(
            summary=summary,
            importance=importance,
            agent_id=agent_id,
            chat_id=chat_id,
            entities=candidate.get("entities", []),
            topics=candidate.get("topics", []),
            embedding=embedding_hex,
        )

        # Track for future duplicate checks this run
        if embedding_vec:
            existing.append((mem_id, embedding_vec))

        stored += 1

        if importance >= 0.8:
            high_importance.append((mem_id, summary))

    # Notify for high-importance memories
    for mem_id, summary in high_importance:
        _notify_high_importance(mem_id, summary)

    logger.info(f"Memory ingest complete: {stored} stored, {len(high_importance)} high-importance")
    return {"stored": stored, "high_importance": len(high_importance)}


def ingest_conversation(
    messages: list[dict],
    agent_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> None:
    """
    Fire-and-forget: extract and store memories from a conversation.
    Runs in a background daemon thread — never blocks the user response.

    Args:
        messages: List of {"role": "user"|"assistant", "content": "..."}
        agent_id: The agent that handled the conversation.
        chat_id: The user's chat ID.
    """
    t = threading.Thread(
        target=_run_ingest,
        args=(messages, agent_id, chat_id),
        daemon=True,
        name="memory-ingest",
    )
    t.start()


def evaluate_relevance(
    surfaced_memory_ids: list[str],
    user_question: str,
    assistant_response: str,
) -> None:
    """
    Fire-and-forget: evaluate which surfaced memories were useful.
    Boosts salience of useful memories, penalises unused ones.

    Args:
        surfaced_memory_ids: IDs of memories shown to the agent.
        user_question: The user's original message.
        assistant_response: The agent's response.
    """
    if not surfaced_memory_ids:
        return

    def _run():
        hive = HiveMindDB()
        client = _get_gemini_client()

        memories = [hive.get_memory_by_id(mid) for mid in surfaced_memory_ids]
        memories = [m for m in memories if m]

        mem_text = "\n".join(
            f"[{m['id'][:8]}] {m['summary']}" for m in memories
        )

        prompt = f"""You are evaluating which AI memories were useful for answering a question.

Question: {user_question}

Response given: {assistant_response}

Memories that were surfaced:
{mem_text}

Return ONLY valid JSON:
{{
  "useful": ["memory_id_prefix_1", "memory_id_prefix_2"],
  "unused": ["memory_id_prefix_3"]
}}

Use the first 8 characters of the ID shown in brackets.
"""
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(response.text.strip())
        except Exception as e:
            logger.warning(f"Relevance evaluation failed: {e}")
            return

        id_map = {m["id"][:8]: m["id"] for m in memories}

        for short_id in result.get("useful", []):
            full_id = id_map.get(short_id)
            if full_id:
                mem = hive.get_memory_by_id(full_id)
                if mem:
                    new_sal = min(5.0, mem["salience"] + 0.1)
                    hive.update_salience(full_id, new_sal)
                    hive.update_last_accessed(full_id)

        for short_id in result.get("unused", []):
            full_id = id_map.get(short_id)
            if full_id:
                mem = hive.get_memory_by_id(full_id)
                if mem:
                    new_sal = max(0.05, mem["salience"] - 0.05)
                    hive.update_salience(full_id, new_sal)

    t = threading.Thread(target=_run, daemon=True, name="relevance-eval")
    t.start()
