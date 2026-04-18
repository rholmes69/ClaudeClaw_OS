"""Browser Skill — agent-browser CLI wrapper

Gives agents full browser automation via the agent-browser CLI:
  navigate pages, snapshot elements, click, fill forms, screenshot, extract text.

Usage: import BROWSER_TOOLS and execute_browser_tool into any agent.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds per command

# ── Tool definition ───────────────────────────────────────────────────────────

BROWSER_TOOLS = [
    {
        "name": "browser",
        "description": (
            "Control a real Chrome browser via the agent-browser CLI. "
            "Use this to open URLs, read page content, click buttons, fill forms, "
            "take screenshots, and extract data from live web pages.\n\n"
            "Workflow:\n"
            "1. open <url> — navigate to a page\n"
            "2. snapshot -i — get interactive element refs (@e1, @e2, …)\n"
            "3. click/fill/get using those refs\n"
            "4. Re-snapshot after navigation or DOM changes\n\n"
            "Common commands (omit 'agent-browser' prefix):\n"
            "  open https://example.com\n"
            "  snapshot -i\n"
            "  get text @e1\n"
            "  get text body\n"
            "  click @e3\n"
            "  fill @e2 \"search query\"\n"
            "  screenshot\n"
            "  wait --load networkidle\n"
            "  close"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The agent-browser command to run, WITHOUT the 'agent-browser' prefix. "
                        "Examples: 'open https://bbc.com', 'snapshot -i', 'get text body', "
                        "'click @e2', 'fill @e1 \"hello\"', 'screenshot'"
                    ),
                }
            },
            "required": ["command"],
        },
    }
]


# ── Execution ─────────────────────────────────────────────────────────────────

def execute_browser_tool(name: str, inputs: dict) -> str:
    """Execute an agent-browser command and return its output."""
    if name != "browser":
        return f"[Unknown tool: {name}]"

    command = (inputs.get("command") or "").strip()
    if not command:
        return "[Error: no command provided]"

    full_cmd = f"agent-browser {command}"
    logger.info(f"Browser: {full_cmd}")

    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout or "").strip()
        err    = (result.stderr or "").strip()

        if result.returncode != 0 and not output:
            return f"[Error (exit {result.returncode})]: {err or 'No output'}"

        # Return stdout, and append stderr if it contains useful info
        if err and result.returncode != 0:
            return f"{output}\n[stderr]: {err}".strip()
        return output or "(no output)"

    except subprocess.TimeoutExpired:
        return f"[Timeout: command took longer than {_TIMEOUT}s]"
    except Exception as exc:
        return f"[Error running browser command: {exc}]"
