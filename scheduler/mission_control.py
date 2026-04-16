"""Mission Control — Proactive task scheduler and mission queue.

Two systems in one:
  1. Cron scheduler: polls every 60 seconds for due tasks, executes them
     through the agent system, then computes the next run time.
  2. Mission queue: one-shot async tasks processed in priority order,
     one per tick after scheduled tasks.

On startup, resets any tasks stuck in 'running' state from a prior crash.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from hive_mind.db import HiveMindDB

load_dotenv()

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60          # seconds between scheduler ticks
TASK_TIMEOUT  = 10 * 60     # 10-minute hard timeout per task

BOT_TOKEN         = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_IDS  = [
    c.strip() for c in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if c.strip()
]

_running = False
_thread: Optional[threading.Thread] = None


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _notify(chat_id: Optional[str], text: str) -> None:
    """Send a Telegram message. Uses first allowed chat ID if none supplied."""
    target = chat_id or (ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else None)
    if not target or not BOT_TOKEN:
        logger.debug(f"[MissionControl] notify skipped (no chat target): {text[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": target, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"[MissionControl] Telegram notify failed: {e}")


def _compute_next_run(cron_expression: str) -> str:
    """Return the next ISO timestamp for a cron expression using APScheduler."""
    try:
        trigger = CronTrigger.from_crontab(cron_expression, timezone="UTC")
        now = datetime.now(timezone.utc)
        next_fire = trigger.get_next_fire_time(None, now)
        return next_fire.isoformat() if next_fire else now.isoformat()
    except Exception as e:
        logger.error(f"[MissionControl] cron parse error '{cron_expression}': {e}")
        # Fallback: 1 hour from now
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _execute_task(agent_id: str, prompt: str, chat_id: Optional[str]) -> str:
    """
    Execute a task prompt via the agent system.
    Returns the response string or an error message.
    """
    result_holder = {}

    def _run():
        try:
            from sdk_bridge.main_agent import MainAgent
            agent = MainAgent()
            # Prepend context so the agent knows this is a scheduled task
            full_prompt = (
                f"[SCHEDULED TASK — agent: {agent_id}]\n{prompt}"
            )
            result_holder["response"] = agent.receive(full_prompt, chat_id=chat_id)
        except Exception as e:
            logger.error(f"[MissionControl] task execution error: {e}")
            result_holder["error"] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=TASK_TIMEOUT)

    if t.is_alive():
        return "[TIMEOUT] Task exceeded the 10-minute execution limit."

    if "error" in result_holder:
        return f"[ERROR] {result_holder['error']}"

    return result_holder.get("response", "[No response]")


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler tick
# ─────────────────────────────────────────────────────────────────────────────

def _process_scheduled_tasks(hive: HiveMindDB) -> None:
    """Check for due tasks and execute them."""
    due = hive.get_due_tasks()
    for task in due:
        task_id  = task["id"]
        agent_id = task["agent_id"] or "ops"
        chat_id  = task["chat_id"]
        prompt   = task["prompt"]
        schedule = task["schedule"]

        logger.info(f"[MissionControl] Running scheduled task {task_id[:8]}: {prompt[:60]}")
        hive.mark_task_running(task_id)

        result = _execute_task(agent_id, prompt, chat_id)
        next_run = _compute_next_run(schedule)

        if result.startswith("[TIMEOUT]") or result.startswith("[ERROR]"):
            hive.set_task_error(task_id, result)
            _notify(chat_id, f"⚠️ *Scheduled task failed*\n`{prompt[:80]}`\n\n{result}")
            hive.log("mission_control", task=f"[scheduled:{task_id[:8]}] {prompt[:60]}", error=result)
        else:
            hive.update_task_after_run(task_id, result, next_run)
            _notify(chat_id, f"✅ *Scheduled task complete*\n`{prompt[:80]}`\n\n{result[:500]}")
            hive.log("mission_control", task=f"[scheduled:{task_id[:8]}] {prompt[:60]}", result=result[:200])


def _process_mission_queue(hive: HiveMindDB) -> None:
    """Process one queued mission per tick (highest priority first)."""
    mission = hive.get_next_queued_mission()
    if not mission:
        return

    mission_id    = mission["id"]
    title         = mission["title"]
    agent_id      = mission.get("assigned_agent") or "ops"
    prompt        = mission["prompt"]
    priority      = mission["priority"]

    logger.info(f"[MissionControl] Running mission {mission_id[:8]} (p{priority}): {title}")
    hive.mark_mission_running(mission_id)

    # Use first allowed chat ID as the notification target for missions
    chat_id = ALLOWED_CHAT_IDS[0] if ALLOWED_CHAT_IDS else None

    result = _execute_task(agent_id, prompt, chat_id)

    if result.startswith("[TIMEOUT]") or result.startswith("[ERROR]"):
        hive.fail_mission(mission_id, result)
        _notify(chat_id, f"⚠️ *Mission failed*: _{title}_\n\n{result}")
        hive.log("mission_control", task=f"[mission:{mission_id[:8]}] {title}", error=result)
    else:
        hive.complete_mission(mission_id, result)
        _notify(chat_id, f"✅ *Mission complete*: _{title}_\n\n{result[:500]}")
        hive.log("mission_control", task=f"[mission:{mission_id[:8]}] {title}", result=result[:200])


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def start_mission_control() -> None:
    """Start the Mission Control background scheduler (singleton, non-blocking)."""
    global _running, _thread

    if _running:
        logger.warning("[MissionControl] Already running.")
        return

    _running = True

    def _loop():
        hive = HiveMindDB()

        # Recover stuck tasks from a previous crash
        stuck = hive.reset_stuck_tasks() + hive.reset_stuck_missions()
        if stuck:
            logger.info(f"[MissionControl] Reset {stuck} stuck task(s) from prior session.")

        logger.info("[MissionControl] Scheduler started. Polling every 60 seconds.")
        while _running:
            try:
                _process_scheduled_tasks(hive)
                _process_mission_queue(hive)
            except Exception as e:
                logger.error(f"[MissionControl] Tick error: {e}")
            time.sleep(POLL_INTERVAL)

        logger.info("[MissionControl] Scheduler stopped.")

    _thread = threading.Thread(target=_loop, daemon=True, name="mission-control")
    _thread.start()


def stop_mission_control() -> None:
    """Signal the Mission Control scheduler to stop after the current tick."""
    global _running
    _running = False


def create_scheduled_task(
    prompt: str,
    schedule: str,
    agent_id: str = "ops",
    chat_id: Optional[str] = None,
) -> dict:
    """
    Create a new scheduled task.

    Args:
        prompt: The task instruction to execute on schedule.
        schedule: Standard 5-field cron expression, e.g. "0 9 * * 1-5".
        agent_id: Which agent should handle the task.
        chat_id: Telegram chat ID for completion notifications.

    Returns:
        dict with task_id, next_run.
    """
    hive = HiveMindDB()
    next_run = _compute_next_run(schedule)
    task_id  = hive.insert_scheduled_task(
        agent_id=agent_id,
        prompt=prompt,
        schedule=schedule,
        next_run=next_run,
        chat_id=chat_id,
    )
    logger.info(f"[MissionControl] Created scheduled task {task_id[:8]}: {prompt[:60]}")
    return {"task_id": task_id, "next_run": next_run, "schedule": schedule}


def queue_mission(
    title: str,
    prompt: str,
    assigned_agent: Optional[str] = None,
    priority: int = 3,
) -> dict:
    """
    Add a one-shot mission to the async queue.

    Args:
        title: Short display title.
        prompt: Full task instruction.
        assigned_agent: Optional agent override. None = route via main agent.
        priority: 1 (highest) through 5 (lowest). Default 3 (normal).

    Returns:
        dict with mission_id, priority.
    """
    hive = HiveMindDB()
    mission_id = hive.insert_mission(
        title=title,
        prompt=prompt,
        assigned_agent=assigned_agent,
        priority=max(1, min(5, priority)),
    )
    logger.info(f"[MissionControl] Queued mission {mission_id[:8]} (p{priority}): {title}")
    return {"mission_id": mission_id, "priority": priority}
