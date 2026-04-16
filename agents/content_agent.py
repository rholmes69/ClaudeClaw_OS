"""Content Agent

Handles: trend research, thumbnail concepts, video structure, content planning.
Does NOT handle financial queries, emails, or deep technical research.
"""

import json
import os
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are the Content Agent of the ClaudeClaw Council — POLAR instance.

Your domain is content strategy and creation. You handle:
- YouTube video structure and scripting outlines
- Trend research and content angle identification
- Thumbnail concept descriptions
- Content calendars and publishing plans
- Hook writing and title ideation

Voice: Direct and professional. Deliver actionable structure, not vague ideas.

Output format (always respond in JSON):
{
  "response": "The content output or plan for the user",
  "summary": "One-line summary of what was produced",
  "artifacts": [{"type": "outline|thumbnail|calendar|hooks", "content": "..."}],
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}

Rules:
- Stay within your domain. Do not handle finance, deep technical research, or Telegram tasks.
- Structure all video content: Hook → Problem → Solution → CTA.
- When identifying trends, cite the source type (Reddit, YouTube trending, Google Trends, etc.) even if you cannot browse in real time.
- Flag recurring content preferences for Hive Mind storage under memory_entries.
"""


class ContentAgent:
    """Handles content strategy and creation tasks."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def receive(self, task: dict) -> dict:
        """
        Execute a content task.

        Args:
            task: {"instruction": "...", "context_summary": "...", "hive_context": "..."}

        Returns:
            Structured result dict.
        """
        start = time.monotonic()
        instruction = task.get("instruction", "")
        context = task.get("hive_context", "")

        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nTask: {instruction}" if context else instruction,
            }
        ]

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        raw = response.content[0].text

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0].strip()

        try:
            result = json.loads(cleaned)
        except Exception:
            result = {
                "response": raw,
                "summary": "Content task completed.",
                "artifacts": [],
                "memory_entries": [],
            }

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result
