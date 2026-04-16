"""Research Agent

Handles: deep web searches, technical documentation analysis,
competitive research, and data gathering.

Skills:
  - browser: full Chrome automation via agent-browser CLI
  - bbc_briefing: fetch BBC News and save to outputs/
"""

import json
import os
import time

import anthropic
from dotenv import load_dotenv

from skills.browser import BROWSER_TOOLS, execute_browser_tool
from skills.bbc_briefing import BBC_BRIEFING_TOOL, execute_bbc_tool

load_dotenv()

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are the Research Agent of the ClaudeClaw Council — POLAR instance.

Your domain is research and information gathering. You handle:
- Deep analysis of technical documentation
- Competitive landscape research
- Technology evaluation and comparison
- Fact-finding and source synthesis
- Data gathering for decision support

You have the following tools:
- browser: open URLs, snapshot pages, extract text, click, fill forms
- bbc_briefing: fetch the latest BBC News and save a briefing txt file to outputs/

When asked to run a BBC briefing or news briefing, call the bbc_briefing tool directly.
When researching a topic, use the browser tool to open relevant pages and extract content.

Voice: Direct and professional. Lead with findings, support with evidence.

Output format (always respond in JSON):
{
  "response": "The research findings formatted for the user",
  "summary": "One-line summary of what was found",
  "findings": [{"topic": "...", "finding": "...", "confidence": "high|medium|low"}],
  "sources": ["source type or URL if known"],
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}

Rules:
- Stay within your domain. Do not handle scripts, finance, or scheduling.
- Always flag confidence level for each finding.
- If you cannot verify a fact, mark it as low confidence and say so explicitly.
- Never fabricate sources. If you don't have a real source, describe the source type.
- Flag verified facts worth persisting under memory_entries.
"""

_TOOLS = BROWSER_TOOLS + [BBC_BRIEFING_TOOL]
_MAX_TOOL_ROUNDS = 8


class ResearchAgent:
    """Handles deep research and information gathering tasks."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def receive(self, task: dict) -> dict:
        start       = time.monotonic()
        instruction = task.get("instruction", "")
        context     = task.get("hive_context", "")

        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nResearch task: {instruction}"
                if context else f"Research task: {instruction}",
            }
        ]

        response = None
        for _ in range(_MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=_TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "bbc_briefing":
                        output = execute_bbc_tool(block.name, block.input)
                    else:
                        output = execute_browser_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",       "content": tool_results})

        # Extract final text
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
                "summary": "Research task completed.",
                "findings": [],
                "sources": [],
                "memory_entries": [],
            }

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result
