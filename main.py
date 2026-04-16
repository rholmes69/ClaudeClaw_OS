"""ClaudeClaw OS — POLAR Entry Point

Starts all active services based on environment configuration.

Usage:
    python main.py                      # start all services (default)
    python main.py --telegram           # main bot only
    python main.py --dashboard          # dashboard only
    python main.py --agent comms        # start comms specialist bot
    python main.py --agent research     # start research specialist bot
"""

import argparse
import logging
import os
import sys
import threading

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("polar")


def start_telegram():
    from channels.telegram import run_bot
    logger.info("Starting Telegram channel...")
    run_bot()


def start_dashboard():
    from dashboard.app import run_dashboard
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    logger.info(f"Starting Dashboard on port {port}...")
    run_dashboard()


def start_war_room_voice():
    from war_room.voice import WarRoomVoice
    voice = WarRoomVoice()
    voice.startup()


def start_memory_engine():
    from hive_mind.memory_consolidate import start_consolidation_loop
    logger.info("Starting Memory v2 consolidation engine...")
    start_consolidation_loop()


def start_mission_control():
    from scheduler.mission_control import start_mission_control as _start
    logger.info("Starting Mission Control scheduler...")
    _start()


def start_agent_bot(agent_id: str):
    from channels.agent_bot import run_agent_bot
    logger.info(f"Starting specialist bot for agent '{agent_id}'...")
    run_agent_bot(agent_id)


def main():
    parser = argparse.ArgumentParser(description="ClaudeClaw OS — POLAR")
    parser.add_argument("--telegram",        action="store_true", help="Start main Telegram bot")
    parser.add_argument("--dashboard",       action="store_true", help="Start web dashboard")
    parser.add_argument("--war-room",        action="store_true", help="Enable War Room voice")
    parser.add_argument("--mission-control", action="store_true", help="Start Mission Control scheduler")
    parser.add_argument("--agent",           type=str,            help="Start a specialist agent bot by ID (e.g. comms, research)")
    parser.add_argument("--all",             action="store_true", help="Start all services")
    args = parser.parse_args()

    # --agent mode: launch a single specialist bot (blocking, nothing else starts)
    if args.agent:
        start_agent_bot(args.agent)
        return

    # Default to --all if nothing specified
    if not any([args.telegram, args.dashboard, args.war_room, args.mission_control, args.all]):
        args.all = True

    threads = []

    if args.war_room or args.all:
        start_war_room_voice()

    # Mission Control runs as a background daemon thread (non-blocking)
    if args.mission_control or args.all:
        start_mission_control()

    if args.dashboard or args.all:
        t = threading.Thread(target=start_dashboard, daemon=True, name="dashboard")
        t.start()
        threads.append(t)

    if args.telegram or args.all:
        # Main Telegram bot is blocking — run in main thread last
        start_telegram()
    else:
        # Keep alive if only dashboard/scheduler is running
        for t in threads:
            t.join()


if __name__ == "__main__":
    main()
