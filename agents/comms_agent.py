"""Comms Agent

Handles: scriptwriting, emails, Telegram notifications.
Has browser skill: can open URLs, read pages, and interact with live web content
to inform content creation.
Does NOT handle financial queries or research tasks.
"""

import json
import os
import time

import anthropic
from dotenv import load_dotenv

from skills.browser import BROWSER_TOOLS, execute_browser_tool

load_dotenv()

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are the Comms Agent of the ClaudeClaw Council — POLAR instance.

Your domain is communication. You handle:
- Scriptwriting (YouTube, podcast, social media scripts)
- Email drafting and formatting
- Telegram message composition
- Notification copy

You have a browser tool that controls a real Chrome browser. Use it when the task
benefits from live web content — e.g.:
- Researching a topic before writing a script
- Reading a competitor's page for reference
- Checking current headlines for a news-based notification
- Extracting product info from a URL to write about

Browser workflow:
1. browser("open <url>") — navigate
2. browser("snapshot -i") — discover element refs
3. browser("get text body") — read page text
4. browser("close") — always close when done

Voice: Direct and professional. No fluff.

Output format (always respond in JSON):
{
  "response": "The communication output or confirmation message for the user",
  "summary": "One-line summary of what was produced",
  "artifacts": [{"type": "script|email|message", "content": "..."}],
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}

Rules:
- Stay within your domain. If asked to do finance or ops tasks, return an error.
- Always produce clean, formatted output suitable for immediate use.
- Flag any information worth storing in the Hive Mind under memory_entries.
- Always close the browser session when finished browsing.
"""

_MAX_TOOL_ROUNDS = 8  # enough for multi-step browsing sequences


class CommsAgent:
    """Handles all communication tasks, with browser automation capability."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

        # Tool execution loop
        response = None
        for _ in range(_MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=BROWSER_TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                break

            # Execute each browser command the model called
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = execute_browser_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",       "content": tool_results})

        # Extract the final text response
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
                "summary": "Comms task completed.",
                "artifacts": [],
                "memory_entries": [],
            }

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result
