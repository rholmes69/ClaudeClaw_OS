"""Hive Mind — Memory Consolidation Engine (v2)

Background job that runs every 30 minutes:
  1. Scans unconsolidated memories (>= 3 required)
  2. Sends to Gemini Flash for pattern + contradiction analysis
  3. Resolves contradictions via supersession (newer wins)
  4. Stores consolidation insights to DB
  5. Marks processed memories as consolidated

Also runs daily salience decay on startup.
"""

import json
import logging
import os
import threading
import time
from typing import Optional

from google import genai
from google.genai import types as genai_types

from hive_mind.db import HiveMindDB

logger = logging.getLogger(__name__)

CONSOLIDATION_INTERVAL = 30 * 60  # 30 minutes
MIN_UNCONSOLIDATED = 3

CONSOLIDATION_PROMPT = """You are a memory consolidation engine for an AI operating system.

Analyze the memories below and:
1. Find cross-cutting patterns and recurring themes
2. Identify connections between separate memories
3. Flag contradictions (where a newer memory contradicts an older one)
4. Produce a concise insight summary

Memories:
{memories}

Return ONLY valid JSON:
{{
  "insights": "concise paragraph summarizing key patterns and themes",
  "patterns": ["pattern or recurring theme 1", "pattern 2"],
  "contradictions": [
    {{
      "old_memory_id": "id of the older, now-superseded memory",
      "new_memory_id": "id of the newer, correct memory",
      "resolution": "brief explanation of how they conflict and which is correct"
    }}
  ]
}}

Rules:
- insights must be under 200 words
- Only flag real contradictions, not just different topics
- If no contradictions exist, return an empty array
- If no clear patterns exist, return an empty array
"""


class ConsolidationEngine:
    """Background memory consolidation for a specific agent."""

    def __init__(self, agent_id: Optional[str] = None):
        self.agent_id = agent_id
        self.hive = HiveMindDB()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _get_client(self) -> genai.Client:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        return genai.Client(api_key=api_key)

    def run_once(self) -> dict:
        """Run a single consolidation pass. Returns summary dict."""
        memories = self.hive.get_unconsolidated_memories(agent_id=self.agent_id)

        if len(memories) < MIN_UNCONSOLIDATED:
            logger.debug(
                f"Consolidation skipped: only {len(memories)} unconsolidated memories "
                f"(need {MIN_UNCONSOLIDATED})"
            )
            return {"skipped": True, "reason": "insufficient_memories", "count": len(memories)}

        logger.info(f"Consolidating {len(memories)} memories for agent={self.agent_id}")

        mem_text = "\n".join(
            f"[{m['id']}] (importance={m['importance']:.2f}) {m['summary']}"
            for m in memories
        )

        try:
            client = self._get_client()
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=CONSOLIDATION_PROMPT.format(memories=mem_text),
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(response.text.strip())
        except Exception as e:
            logger.error(f"Consolidation Gemini call failed: {e}")
            return {"error": str(e)}

        # Resolve contradictions via supersession
        for contradiction in result.get("contradictions", []):
            old_id = contradiction.get("old_memory_id", "").strip()
            new_id = contradiction.get("new_memory_id", "").strip()
            if old_id and new_id and old_id != new_id:
                try:
                    self.hive.set_superseded_by(old_id, new_id)
                    logger.info(f"Memory supersession: {old_id[:8]} → {new_id[:8]}")
                except Exception as e:
                    logger.warning(f"Supersession failed for {old_id}: {e}")

        # Store consolidation
        memory_ids = [m["id"] for m in memories]
        con_id = self.hive.insert_consolidation(
            agent_id=self.agent_id or "global",
            insights=result.get("insights", ""),
            patterns=result.get("patterns", []),
            contradictions=result.get("contradictions", []),
            memory_ids=memory_ids,
        )

        # Mark memories as consolidated
        self.hive.mark_memories_consolidated(memory_ids)

        logger.info(
            f"Consolidation complete: id={con_id[:8]}, "
            f"{len(result.get('patterns', []))} patterns, "
            f"{len(result.get('contradictions', []))} contradictions resolved"
        )

        return {
            "consolidation_id": con_id,
            "memories_processed": len(memory_ids),
            "patterns": len(result.get("patterns", [])),
            "contradictions": len(result.get("contradictions", [])),
        }

    def run_decay(self) -> int:
        """Run daily salience decay. Returns number of memories deleted."""
        deleted = self.hive.run_salience_decay()
        if deleted:
            logger.info(f"Salience decay: {deleted} memories hard-deleted (below floor)")
        return deleted

    def _loop(self) -> None:
        """Background loop: consolidate every 30 minutes."""
        # Run decay once on startup
        self.run_decay()

        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Consolidation loop error: {e}")
            self._stop_event.wait(timeout=CONSOLIDATION_INTERVAL)

    def start(self) -> None:
        """Start the background consolidation loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"consolidation-{self.agent_id or 'global'}",
        )
        self._thread.start()
        logger.info(
            f"Consolidation engine started (interval={CONSOLIDATION_INTERVAL}s, "
            f"agent={self.agent_id or 'global'})"
        )

    def stop(self) -> None:
        """Stop the background loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Consolidation engine stopped.")


# Module-level singleton
_engine: Optional[ConsolidationEngine] = None


def start_consolidation_loop(agent_id: Optional[str] = None) -> ConsolidationEngine:
    """Start (or return existing) global consolidation engine."""
    global _engine
    if _engine is None:
        _engine = ConsolidationEngine(agent_id=agent_id)
    _engine.start()
    return _engine


def stop_consolidation_loop() -> None:
    global _engine
    if _engine:
        _engine.stop()
