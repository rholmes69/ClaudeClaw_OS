"""SDK Bridge — Main Agent (Triage Manager)

The Main Agent is a manager, not a doer. It:
  1. Validates inbound chat IDs against the allow-list
  2. Loads session context from the Hive Mind
  3. Uses Claude to classify and route the request
  4. Delegates to the correct specialist agent
  5. Writes results back to the Hive Mind
  6. Returns a concise response to the user
"""

import json
import os
import time
from typing import Optional

import anthropic
from dotenv import load_dotenv

from hive_mind.db import HiveMindDB
from hive_mind.memory_controller import MemoryController
from hive_mind.memory_ingest import evaluate_relevance, ingest_conversation
from sdk_bridge.router import AgentRouter
from sdk_bridge.orchestrator import parse_delegation, post_to_hive

load_dotenv()

MODEL = os.getenv("MAIN_AGENT_MODEL", "claude-sonnet-4-6")
ALLOWED_CHAT_IDS = set(
    os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
)

ROUTING_TOOL = {
    "name": "route_to_agent",
    "description": (
        "Route the user's request to the correct specialist agent. "
        "Always call this tool — never answer directly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["comms", "content", "ops", "research", "finance", "cicd"],
                "description": (
                    "comms: scriptwriting, emails, Telegram notifications, social media copy. "
                    "content: trends, thumbnails, video outlines, content planning. "
                    "ops: scheduling, hive mind updates, project scaffolding, system status. "
                    "research: deep web searches, technical documentation, competitive analysis. "
                    "finance: invoices, expenses, payroll, financial tracking, AP queries. "
                    "cicd: ANYTHING involving git or GitHub — push, pull, clone, commit, "
                    "branches, pull requests, merging, repo management, deploying code, "
                    "version control. If the user mentions GitHub, git, pushing, pulling, "
                    "or committing code, always choose cicd."
                ),
            },
            "task": {
                "type": "string",
                "description": "The full, unambiguous task description to pass to the specialist.",
            },
            "context_summary": {
                "type": "string",
                "description": "Brief summary of any relevant Hive Mind context for this task.",
            },
        },
        "required": ["agent", "task"],
    },
}


class MainAgent:
    """POLAR Main Agent — Triage and delegation manager."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.hive = HiveMindDB()
        self.memory = MemoryController()
        self.router = AgentRouter()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def receive(self, instruction: str, chat_id: Optional[str] = None) -> str:
        """
        Entry point for all inbound requests.

        Args:
            instruction: The user's raw instruction.
            chat_id: Telegram chat ID string (validated against allow-list).

        Returns:
            Final response string for the user.
        """
        # Security: validate chat ID
        if chat_id and not self._is_allowed(chat_id):
            return "Access denied."

        start = time.monotonic()

        # Check for direct delegation syntax: @agent_id: task
        delegation = parse_delegation(instruction)
        if delegation:
            agent_name, task_description = delegation
            try:
                result = self.router.route(agent_name, {
                    "instruction": task_description,
                    "context_summary": "",
                    "hive_context": "",
                })
            except Exception as e:
                return f"[{agent_name.upper()} AGENT ERROR] {e}"
            final_response = result.get("response", "Task completed.")
            post_to_hive(agent_name, "complete", task_description[:120], tags=["main"])
            ingest_conversation(
                messages=[{"role": "user", "content": instruction},
                           {"role": "assistant", "content": final_response}],
                agent_id=agent_name, chat_id=chat_id,
            )
            return final_response

        # Load Hive Mind session context (v2: semantic search on instruction)
        hive_context = self.memory.load_session_context(
            query=instruction, agent_id="main_agent"
        )

        # Deterministic keyword pre-classifier — bypasses LLM routing for
        # unambiguous domain keywords (e.g. git push → always cicd).
        keyword_agent = self._keyword_route(instruction)
        if keyword_agent:
            agent_name      = keyword_agent
            task_description = instruction
            context_summary  = ""
        else:
            # Ask Claude to classify and route
            system  = self._build_system_prompt(hive_context)
            routing = self._classify(instruction, system)
            if routing is None:
                self.hive.log("main_agent", task=instruction, error="Routing classification failed")
                return "I was unable to determine how to handle that request. Please try rephrasing."
            agent_name      = routing["agent"]
            task_description = routing["task"]
            context_summary  = routing.get("context_summary", "")

        # Log routing decision
        self.hive.log("main_agent", task=f"Routing to {agent_name}: {task_description}")

        # Delegate to specialist
        try:
            result = self.router.route(agent_name, {
                "instruction": task_description,
                "context_summary": context_summary,
                "hive_context": hive_context,
            })
        except Exception as e:
            err = str(e)
            self.hive.log("main_agent", task=task_description, error=err)
            return f"[{agent_name.upper()} AGENT ERROR] {err}. The failure has been logged."

        # Write new memories back to Hive Mind
        if result.get("memory_entries"):
            for entry in result["memory_entries"]:
                self.hive.write_memory(
                    category=entry["category"],
                    key=entry["key"],
                    value=entry["value"],
                    source_agent=agent_name,
                )

        duration_ms = int((time.monotonic() - start) * 1000)
        self.hive.log(
            "main_agent",
            task=instruction,
            result=json.dumps(result.get("summary", "")),
            duration_ms=duration_ms,
        )

        final_response = result.get("response", "Task completed.")

        # Post completion to shared Hive Mind log
        post_to_hive(agent_name, "complete", task_description[:120], tags=["main"])

        # Fire-and-forget: extract memories from this exchange
        ingest_conversation(
            messages=[
                {"role": "user", "content": instruction},
                {"role": "assistant", "content": final_response},
            ],
            agent_id=agent_name,
            chat_id=chat_id,
        )

        return final_response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_allowed(self, chat_id: str) -> bool:
        return chat_id.strip() in ALLOWED_CHAT_IDS

    def _keyword_route(self, instruction: str) -> Optional[str]:
        """
        Deterministic keyword pre-classifier. Returns an agent name if the
        instruction contains unambiguous domain keywords, bypassing the LLM
        routing call entirely. Returns None to fall through to LLM routing.
        """
        text = instruction.lower()
        _CICD_KEYWORDS = (
            "git push", "git pull", "git clone", "git commit", "git branch",
            "git checkout", "git merge", "git status", "git log",
            "push to github", "pull from github", "push to origin",
            "push the latest", "push my code", "push changes",
            "pull request", "open a pr", "create a pr", "merge branch",
            "github repo", "github repository", "clone the repo", "clone repo",
            "commit and push", "stage and commit", "push origin",
        )
        if any(kw in text for kw in _CICD_KEYWORDS):
            return "cicd"
        return None

    def _build_system_prompt(self, hive_context: str) -> str:
        with open("prompts/main_agent_v1.md", "r") as f:
            base = f.read()
        return f"{base}\n\n{hive_context}"

    def _classify(self, instruction: str, system: str) -> Optional[dict]:
        """Call Claude with the routing tool to determine delegation target."""
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=system,
            tools=[ROUTING_TOOL],
            tool_choice={"type": "tool", "name": "route_to_agent"},
            messages=[{"role": "user", "content": instruction}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "route_to_agent":
                return block.input

        return None
