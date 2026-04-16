"""Hive Mind — Memory Controller v2

5-layer retrieval stack for session context loading:

  Layer 1 — Semantic search (cosine similarity > 0.3, top 5)
  Layer 2 — FTS5 keyword search (top 5)
  Layer 3 — Recent high-importance (importance >= 0.7, last 48h, top 5)
  Layer 4 — Consolidation insights (latest 3)
  Layer 5 — Conversation history recall (keywords, 7-day window, top 10)

Also handles legacy key-value memory (facts / preferences / context).
"""

import logging
import os
from typing import Optional

from hive_mind.db import HiveMindDB
from hive_mind.embeddings import decode_embedding, generate_embedding, semantic_search

logger = logging.getLogger(__name__)

# Memory nudging config
NUDGE_INTERVAL_TURNS = int(os.getenv("MEMORY_NUDGE_INTERVAL_TURNS", "10"))
NUDGE_INTERVAL_HOURS = int(os.getenv("MEMORY_NUDGE_INTERVAL_HOURS", "2"))


class MemoryController:
    """
    Unified interface for reading and writing Hive Mind memory.
    Used by the Main Agent at the start of every session.
    """

    def __init__(self):
        self.hive = HiveMindDB()

    # ──────────────────────────────────────────────────────────────
    # Session context (called at the start of every agent session)
    # ──────────────────────────────────────────────────────────────

    def load_session_context(
        self,
        query: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """
        Build a context string to inject into agent prompts.

        Args:
            query: Current user message (used for semantic + keyword search).
            agent_id: Filter memories to a specific agent.

        Returns:
            Formatted context string.
        """
        lines = ["=== HIVE MIND SESSION CONTEXT ==="]

        # ── Legacy: pinned facts ──
        pinned = self.hive.read_pinned()
        if pinned:
            lines.append("\n[PINNED FACTS]")
            for m in pinned:
                lines.append(f"  {m['key']}: {m['value']}")

        # ── Legacy: preferences ──
        prefs = self.hive.read_memory(category="preference")
        if prefs:
            lines.append("\n[PREFERENCES]")
            for m in prefs:
                lines.append(f"  {m['key']}: {m['value']}")

        # ── Legacy: active context ──
        ctx = self.hive.read_memory(category="context")
        if ctx:
            lines.append("\n[ACTIVE CONTEXT]")
            for m in ctx:
                lines.append(f"  {m['key']}: {m['value']}")

        # ── Memory v2 retrieval ──
        if query:
            v2_memories = self._retrieve_v2(query, agent_id=agent_id)
            if v2_memories:
                lines.append("\n[RECALLED MEMORIES]")
                seen = set()
                for mem in v2_memories:
                    if mem["id"] in seen:
                        continue
                    seen.add(mem["id"])
                    lines.append(
                        f"  [{mem['importance']:.1f}] {mem['summary']}"
                    )

        # ── Consolidation insights ──
        consolidations = self.hive.get_latest_consolidations(agent_id=agent_id, limit=3)
        if consolidations:
            lines.append("\n[PATTERN INSIGHTS]")
            for c in consolidations:
                if c.get("insights"):
                    lines.append(f"  {c['insights'][:300]}")

        lines.append("\n=================================")
        return "\n".join(lines)

    def _retrieve_v2(
        self,
        query: str,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """Run the 5-layer retrieval stack and return deduplicated results."""
        results: dict[str, dict] = {}  # id → memory dict

        # Layer 1: Semantic search
        try:
            query_emb = generate_embedding(query)
            raw_embeddings = self.hive.get_all_embeddings(agent_id=agent_id)
            candidates = [(mid, decode_embedding(emb)) for mid, emb in raw_embeddings]
            hits = semantic_search(query_emb, candidates, threshold=0.3, top_k=5)
            for mem_id, _score in hits:
                mem = self.hive.get_memory_by_id(mem_id)
                if mem and mem["id"] not in results:
                    results[mem["id"]] = mem
                    self.hive.update_last_accessed(mem["id"])
        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")

        # Layer 2: FTS5 keyword search
        try:
            # Extract simple keywords (words > 3 chars)
            keywords = [w for w in query.split() if len(w) > 3]
            if keywords:
                fts_query = " OR ".join(keywords[:5])
                fts_hits = self.hive.search_memories_fts(fts_query, limit=5)
                for mem in fts_hits:
                    if mem["id"] not in results:
                        results[mem["id"]] = mem
        except Exception as e:
            logger.warning(f"FTS search failed: {e}")

        # Layer 3: Recent high-importance
        try:
            recent = self.hive.get_recent_high_importance(
                agent_id=agent_id, min_importance=0.7, hours=48, limit=5
            )
            for mem in recent:
                if mem["id"] not in results:
                    results[mem["id"]] = mem
        except Exception as e:
            logger.warning(f"Recent high-importance retrieval failed: {e}")

        # Layer 5: Conversation history recall
        try:
            keywords = [w for w in query.split() if len(w) > 3]
            if keywords:
                history = self.hive.search_conversation_history(
                    keywords=keywords[:5],
                    agent_id=agent_id,
                    day_window=7,
                    limit=10,
                )
                for mem in history:
                    if mem["id"] not in results:
                        results[mem["id"]] = mem
        except Exception as e:
            logger.warning(f"Conversation history recall failed: {e}")

        # Sort by salience desc
        all_mems = list(results.values())
        all_mems.sort(key=lambda m: m.get("salience", 0), reverse=True)
        return all_mems[:15]

    # ──────────────────────────────────────────────────────────────
    # Legacy write-back (used by main_agent for simple k/v entries)
    # ──────────────────────────────────────────────────────────────

    def write_kv(
        self,
        category: str,
        key: str,
        value: str,
        source_agent: Optional[str] = None,
    ) -> None:
        self.hive.write_memory(
            category=category,
            key=key,
            value=value,
            source_agent=source_agent,
        )

    # ──────────────────────────────────────────────────────────────
    # Legacy wash (kept for backwards compatibility)
    # ──────────────────────────────────────────────────────────────

    def wash(self, conversation_log: str, source_agent: Optional[str] = None) -> dict:
        """
        Legacy method: extract key-value memories from a log string via Gemini.
        New code should use memory_ingest.ingest_conversation() instead.
        """
        import json
        import os
        from google import genai
        from google.genai import types as genai_types

        EXTRACTION_PROMPT = """Extract structured memory from this conversation log.

Return ONLY valid JSON:
{{
  "facts": [{{"key": "...", "value": "...", "pinned": false}}],
  "preferences": [{{"key": "...", "value": "..."}}],
  "context": [{{"key": "...", "value": "...", "ttl_hours": 24}}]
}}

Rules:
- Never include credentials, tokens, or PII
- Only mark pinned=true for critical config facts (name, email, core API endpoints)
- Keys must be snake_case
- Return empty arrays if nothing applies

Log:
{log}
"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"error": "GEMINI_API_KEY not set", "stored": 0}

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=EXTRACTION_PROMPT.format(log=conversation_log),
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            extracted = json.loads(response.text.strip())
        except Exception as e:
            return {"error": str(e), "stored": 0}

        stored = 0
        for item in extracted.get("facts", []):
            self.hive.write_memory("fact", item["key"], str(item["value"]),
                                   pinned=item.get("pinned", False),
                                   ttl_hours=None, source_agent=source_agent)
            stored += 1
        for item in extracted.get("preferences", []):
            self.hive.write_memory("preference", item["key"], str(item["value"]),
                                   ttl_hours=None, source_agent=source_agent)
            stored += 1
        for item in extracted.get("context", []):
            self.hive.write_memory("context", item["key"], str(item["value"]),
                                   ttl_hours=item.get("ttl_hours", 24),
                                   source_agent=source_agent)
            stored += 1

        return {"stored": stored}
