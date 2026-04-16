"""SDK Bridge — Agent Router

Maps task classifications to specialist agent modules.
The Main Agent calls this to delegate work.
"""

from __future__ import annotations
import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.comms_agent import CommsAgent
    from agents.content_agent import ContentAgent
    from agents.ops_agent import OpsAgent
    from agents.research_agent import ResearchAgent

AGENT_MAP = {
    "comms": ("agents.comms_agent", "CommsAgent"),
    "content": ("agents.content_agent", "ContentAgent"),
    "ops": ("agents.ops_agent", "OpsAgent"),
    "research": ("agents.research_agent", "ResearchAgent"),
    "finance": ("agents.finance_agent", "FinanceAgent"),
}


class AgentRouter:
    """Lazy-loads and caches specialist agent instances."""

    def __init__(self):
        self._cache: dict = {}

    def get(self, agent_name: str):
        """Return a cached or freshly instantiated specialist agent."""
        name = agent_name.lower()
        if name not in AGENT_MAP:
            raise ValueError(
                f"Unknown agent: '{name}'. Available: {list(AGENT_MAP.keys())}"
            )
        if name not in self._cache:
            module_path, class_name = AGENT_MAP[name]
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            self._cache[name] = cls()
        return self._cache[name]

    def route(self, agent_name: str, task: dict) -> dict:
        """
        Route a task to the named specialist agent.

        Args:
            agent_name: One of 'comms', 'content', 'ops', 'research'
            task: Structured task dict with at minimum {"instruction": "..."}

        Returns:
            Structured result dict from the specialist agent.
        """
        agent = self.get(agent_name)
        return agent.receive(task)
