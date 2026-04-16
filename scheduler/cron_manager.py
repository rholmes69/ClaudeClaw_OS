"""Cron Manager

Manages scheduled tasks for ClaudeClaw OS using APScheduler.
All cron jobs are registered through this module — never directly.
Job definitions persist to the Hive Mind so they survive restarts.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

from hive_mind.db import HiveMindDB

load_dotenv()

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


class CronManager:
    """Register, list, and remove scheduled tasks."""

    def __init__(self):
        self.scheduler = get_scheduler()
        self.hive = HiveMindDB()
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("CronManager scheduler started.")
        self._restore_jobs()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_cron_job(
        self,
        job_id: str,
        func: Callable,
        cron_expression: str,
        description: str = "",
    ) -> dict:
        """
        Schedule a recurring job with a cron expression.

        Args:
            job_id: Unique identifier for the job.
            func: Callable to execute.
            cron_expression: Standard cron string, e.g. "0 9 * * 1-5"
            description: Human-readable description.

        Returns:
            Job info dict.
        """
        minute, hour, day, month, day_of_week = self._parse_cron(cron_expression)
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day,
            month=month, day_of_week=day_of_week, timezone="UTC"
        )
        self.scheduler.add_job(func, trigger, id=job_id, replace_existing=True)
        self._persist_job(job_id, "cron", cron_expression, description)
        logger.info(f"Cron job '{job_id}' registered: {cron_expression}")
        return {"job_id": job_id, "type": "cron", "expression": cron_expression, "description": description}

    def add_interval_job(
        self,
        job_id: str,
        func: Callable,
        seconds: int,
        description: str = "",
    ) -> dict:
        """Schedule a job to run every N seconds."""
        trigger = IntervalTrigger(seconds=seconds)
        self.scheduler.add_job(func, trigger, id=job_id, replace_existing=True)
        self._persist_job(job_id, "interval", str(seconds), description)
        logger.info(f"Interval job '{job_id}' registered: every {seconds}s")
        return {"job_id": job_id, "type": "interval", "seconds": seconds, "description": description}

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by ID."""
        try:
            self.scheduler.remove_job(job_id)
            self.hive.delete_memory("context", f"cron_job_{job_id}")
            logger.info(f"Job '{job_id}' removed.")
            return True
        except Exception as e:
            logger.warning(f"Could not remove job '{job_id}': {e}")
            return False

    def list_jobs(self) -> list[dict]:
        """Return all currently scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "job_id": job.id,
                "next_run": str(job.next_run_time),
                "trigger": str(job.trigger),
            })
        return jobs

    def shutdown(self) -> None:
        """Gracefully shut down the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("CronManager scheduler stopped.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cron(expr: str) -> tuple:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression (need 5 fields): '{expr}'")
        return tuple(parts)

    def _persist_job(self, job_id: str, job_type: str, expression: str, description: str) -> None:
        self.hive.write_memory(
            category="context",
            key=f"cron_job_{job_id}",
            value=json.dumps({
                "type": job_type,
                "expression": expression,
                "description": description,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }),
            ttl_hours=None,
            source_agent="cron_manager",
        )

    def _restore_jobs(self) -> None:
        """Restore job metadata from Hive Mind on startup (functions must be re-registered)."""
        entries = self.hive.read_memory(category="context")
        restored = 0
        for entry in entries:
            if entry["key"].startswith("cron_job_"):
                restored += 1
        if restored:
            logger.info(f"Found {restored} cron job(s) in Hive Mind — re-register callables manually.")
