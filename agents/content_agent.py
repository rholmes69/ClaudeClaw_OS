"""Content Agent

Handles: trend research, thumbnail concepts, video structure, content planning,
and programmatic video rendering via Remotion.
Does NOT handle financial queries, emails, or deep technical research.
"""

import json
import os
import time
from dotenv import load_dotenv

from skills.remotion import REMOTION_TOOLS, execute_remotion_tool
from sdk_bridge.llm_client import get_llm_client

load_dotenv()

MODEL = "claude-sonnet-4-6"
_MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are the Content Agent of the ClaudeClaw Council — POLAR instance.

Your domain is content strategy and creation. You handle:
- YouTube video structure and scripting outlines
- Trend research and content angle identification
- Thumbnail concept descriptions
- Content calendars and publishing plans
- Hook writing and title ideation
- Programmatic video creation and rendering using Remotion

You have Remotion tools for building and rendering React-based videos:
- remotion_scaffold: Create a new Remotion project
- remotion_render: Render a composition to an mp4 file
- remotion_still: Capture a single frame as an image
- remotion_studio: Instructions to launch the live preview server

When the user asks to create, render, or produce a video programmatically,
use the Remotion tools. For outlines, scripts, and planning tasks, respond directly.

Voice: Direct and professional. Deliver actionable structure, not vague ideas.

Output format (always respond in JSON):
{
  "response": "The content output or plan for the user",
  "summary": "One-line summary of what was produced",
  "artifacts": [{"type": "outline|thumbnail|calendar|hooks|video", "content": "..."}],
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}

Rules:
- Stay within your domain. Do not handle finance, deep technical research, or Telegram tasks.
- Structure all video content: Hook → Problem → Solution → CTA.
- When identifying trends, cite the source type (Reddit, YouTube trending, Google Trends, etc.) even if you cannot browse in real time.
- Flag recurring content preferences for Hive Mind storage under memory_entries.
- Always close Remotion render tasks by reporting the output file path.
"""


class ContentAgent:
    """Handles content strategy, creation, and Remotion video rendering."""

    def __init__(self):
        self.client = get_llm_client(MODEL)

    def receive(self, task: dict) -> dict:
        start       = time.monotonic()
        instruction = task.get("instruction", "")
        context     = task.get("hive_context", "")

        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nTask: {instruction}" if context else instruction,
            }
        ]

        response = None
        for _ in range(_MAX_TOOL_ROUNDS):
            response = self.client.create(
                messages=messages,
                system=SYSTEM_PROMPT,
                tools=REMOTION_TOOLS,
                max_tokens=4096,
            )

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = execute_remotion_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",       "content": tool_results})

        raw = ""
        for block in (response.content if response else []):
            if hasattr(block, "text"):
                raw = block.text
                break

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
