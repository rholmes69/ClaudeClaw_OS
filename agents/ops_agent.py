"""Ops Agent

Handles: financial tracking, task scheduling, Hive Mind updates,
and new project scaffolding.
"""

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from hive_mind.db import HiveMindDB

load_dotenv()

MODEL = "claude-sonnet-4-6"
PROJECTS_ROOT = os.getenv("PROJECTS_ROOT", "./projects")
SCAFFOLD_TEMPLATE = "./scaffold"

SYSTEM_PROMPT = """You are the Ops Agent of the ClaudeClaw Council — POLAR instance.

Your domain is operations. You handle:
- Financial tracking and expense categorization
- Task scheduling and cron job registration
- Hive Mind read/write operations
- New project workspace scaffolding
- Status reports and operational summaries

Voice: Direct and professional. Be precise with numbers and dates.

Output format (always respond in JSON):
{
  "response": "The result or confirmation for the user",
  "summary": "One-line summary of what was done",
  "action": "scaffold|finance|schedule|hive_update|status",
  "action_data": {},
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}

Rules:
- Stay within your domain. Do not handle scripts, content, or research.
- For project scaffolding, always confirm the project name before creating.
- Never overwrite an existing project folder.
- Financial entries must include: amount, category, date, description.
- Flag any operational data worth persisting under memory_entries.
"""

SCAFFOLD_DIRS = ["prompts", "hive_mind", "outputs", "assets", "logs"]


class OpsAgent:
    """Handles operations, scheduling, finance, and project scaffolding."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.hive = HiveMindDB()

    def receive(self, task: dict) -> dict:
        """
        Execute an ops task.

        Args:
            task: {"instruction": "...", "context_summary": "...", "hive_context": "..."}

        Returns:
            Structured result dict.
        """
        start = time.monotonic()
        instruction = task.get("instruction", "").lower()

        # Intercept project scaffold requests directly
        if any(phrase in instruction for phrase in [
            "new project", "create project", "scaffold", "spin up", "new workspace"
        ]):
            return self._scaffold_project(task)

        # All other ops tasks go to Claude
        context = task.get("hive_context", "")
        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nTask: {task.get('instruction', '')}"
                if context else task.get("instruction", ""),
            }
        ]

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=2048,
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
                "summary": "Ops task completed.",
                "action": "ops",
                "action_data": {},
                "memory_entries": [],
            }

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result

    def _scaffold_project(self, task: dict) -> dict:
        """Create a new project workspace from the scaffold template."""
        instruction = task.get("instruction", "")

        # Extract project name from instruction using Claude
        extract_response = self.client.messages.create(
            model=MODEL,
            max_tokens=64,
            system="Extract only the project name from the user's instruction. "
                   "Return ONLY the sanitized name: lowercase, hyphens instead of spaces, "
                   "no special characters. Nothing else.",
            messages=[{"role": "user", "content": instruction}],
        )
        raw_name = extract_response.content[0].text.strip().lower()
        sanitized = raw_name.replace(" ", "-").replace("_", "-")
        sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")

        project_path = Path(PROJECTS_ROOT) / sanitized

        # Check for existing project
        if project_path.exists():
            return {
                "response": (
                    f"A project folder already exists at `{project_path}`. "
                    "Choose a different name or confirm you want to use the existing folder."
                ),
                "summary": "Project already exists.",
                "action": "scaffold",
                "action_data": {"name": sanitized, "path": str(project_path), "status": "conflict"},
                "memory_entries": [],
            }

        # Check existing Hive Mind registry
        existing = self.hive.get_project(sanitized)
        if existing:
            return {
                "response": (
                    f"Project `{sanitized}` is already registered in the Hive Mind "
                    f"with status `{existing['status']}`. Use a different name or "
                    "ask to reactivate the existing project."
                ),
                "summary": "Project already registered in Hive Mind.",
                "action": "scaffold",
                "action_data": existing,
                "memory_entries": [],
            }

        # Create directory structure
        project_path.mkdir(parents=True, exist_ok=True)
        for subdir in SCAFFOLD_DIRS:
            (project_path / subdir).mkdir(exist_ok=True)

        # Copy scaffold template files if available
        scaffold_src = Path(SCAFFOLD_TEMPLATE)
        if scaffold_src.exists():
            for item in scaffold_src.iterdir():
                dest = project_path / item.name
                if not dest.exists():
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)

        # Write CLAUDE.md
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        claude_md = (
            f"# {sanitized.upper()}\n\n"
            f"ClaudeClaw OS project workspace.\n\n"
            f"**Created:** {now_str}\n"
            f"**Status:** active\n\n"
            f"## Purpose\n\n"
            f"[Describe this project here.]\n"
        )
        (project_path / "CLAUDE.md").write_text(claude_md)

        # Write blank .env
        env_template = Path("scaffold/.env.template")
        if env_template.exists():
            shutil.copy2(env_template, project_path / ".env")
        else:
            (project_path / ".env").write_text("# Project secrets — never commit\n")

        # Register in Hive Mind
        abs_path = str(project_path.resolve())
        self.hive.register_project(name=sanitized, path=abs_path)

        return {
            "response": (
                f"Project `{sanitized}` created at `{abs_path}`.\n\n"
                f"Structure:\n"
                + "\n".join(f"  {sanitized}/{d}/" for d in SCAFFOLD_DIRS)
                + f"\n  {sanitized}/CLAUDE.md\n  {sanitized}/.env\n\n"
                f"Registered in Hive Mind. Ready to go."
            ),
            "summary": f"Project '{sanitized}' scaffolded and registered.",
            "action": "scaffold",
            "action_data": {
                "name": sanitized,
                "path": abs_path,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "active",
            },
            "memory_entries": [
                {
                    "category": "fact",
                    "key": f"project_{sanitized}_path",
                    "value": abs_path,
                }
            ],
        }
