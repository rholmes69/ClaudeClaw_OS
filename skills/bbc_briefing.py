"""BBC News Briefing Skill

Opens BBC News with agent-browser, extracts the page text,
and saves a timestamped briefing to outputs/.

Exposed as an Anthropic tool so any agent can call it.
"""

import logging
import os
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_OUTPUTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "outputs"
)
_TIMEOUT = 40  # seconds per browser command

# ── Tool definition ───────────────────────────────────────────────────────────

BBC_BRIEFING_TOOL = {
    "name": "bbc_briefing",
    "description": (
        "Fetch the latest BBC News headlines using a real browser, then save "
        "a formatted briefing to a txt file in outputs/. "
        "Returns the saved file path and a short preview of the content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "max_chars": {
                "type": "integer",
                "description": "Max characters of page content to capture (default 6000).",
                "default": 6000,
            }
        },
        "required": [],
    },
}


# ── Execution ─────────────────────────────────────────────────────────────────

def _run(cmd: str) -> str:
    """Run a single agent-browser command and return stdout."""
    try:
        r = subprocess.run(
            f"agent-browser {cmd}",
            shell=True, capture_output=True, text=True, timeout=_TIMEOUT,
        )
        return (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as exc:
        return f"[error: {exc}]"


def run_briefing(max_chars: int = 6000) -> str:
    """
    Browse BBC News, save briefing to outputs/, return file path + preview.
    """
    os.makedirs(_OUTPUTS_DIR, exist_ok=True)

    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    filepath  = os.path.join(_OUTPUTS_DIR, f"bbc_briefing_{today}.txt")

    logger.info("[BBCBriefing] Opening BBC News…")

    # Navigate and wait for content
    _run("open https://www.bbc.com/news")
    _run("wait --load networkidle")

    # Extract page text
    content = _run("get text body")
    _run("close")

    if not content or content.startswith("["):
        return f"[Error fetching BBC News: {content}]"

    # Trim to max_chars
    trimmed = content[:max_chars]

    # Format the file
    header = (
        f"BBC NEWS BRIEFING\n"
        f"Generated: {timestamp}\n"
        f"Source: https://www.bbc.com/news\n"
        f"{'=' * 60}\n\n"
    )
    body = header + trimmed

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(body)

    preview = trimmed[:300].replace("\n", " ").strip()
    logger.info(f"[BBCBriefing] Saved to {filepath}")
    return f"Briefing saved to: {filepath}\n\nPreview: {preview}…"


def execute_bbc_tool(name: str, inputs: dict) -> str:
    """Dispatch function for use in agent tool loops."""
    if name == "bbc_briefing":
        return run_briefing(inputs.get("max_chars", 6000))
    return f"[Unknown tool: {name}]"
