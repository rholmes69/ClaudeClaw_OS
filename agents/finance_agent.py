"""Finance / AP Agent (Angela)

Handles: invoices, expense tracking, payroll queries, financial summaries.
Does NOT handle communications, content, or research tasks.
"""

import json
import os
import time

from dotenv import load_dotenv

from sdk_bridge.llm_client import get_llm_client

load_dotenv()

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Angela, the Accounts Payable specialist of the ClaudeClaw Council — POLAR instance.

Your domain is finance. You handle:
- Invoice tracking and categorization
- Expense logging and reconciliation
- Payroll queries and summaries
- Financial status reports

Voice: Direct and professional. Be precise with numbers and dates. No fluff.

Output format (always respond in JSON):
{
  "response": "The financial output or confirmation for the user",
  "summary": "One-line summary of what was done",
  "artifacts": [{"type": "invoice|expense|payroll|report", "content": "..."}],
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}

Rules:
- Stay within your domain. If asked to write scripts, do research, or manage operations, return an error.
- Always include amounts as numbers with currency symbols.
- Flag any financial data worth storing in the Hive Mind under memory_entries.
"""


class FinanceAgent:
    """Handles accounts payable, expense tracking, and financial queries."""

    def __init__(self):
        self.client = get_llm_client(MODEL)

    def receive(self, task: dict) -> dict:
        start = time.monotonic()
        instruction = task.get("instruction", "")
        context = task.get("hive_context", "")

        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nTask: {instruction}" if context else instruction,
            }
        ]

        response = self.client.create(
            messages=messages,
            system=SYSTEM_PROMPT,
            max_tokens=2048,
        )

        raw = next((b.text for b in response.content if b.type == "text"), "")

        # Strip markdown code fences if Claude wrapped the JSON
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
                "summary": "Finance task completed.",
                "artifacts": [],
                "memory_entries": [],
            }

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result
