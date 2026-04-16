"""Telegram Channel

Inbound/outbound Telegram bot for ClaudeClaw OS — POLAR instance.
Validates chat IDs, passes messages to Main Agent, sends responses back.

Security layers (Pack 5):
  1. Chat ID allow-list (inbound gate)
  2. Kill phrase check (pre-processing)
  3. PIN lock check (pre-processing)
  4. Exfiltration guard (outbound scan before every send)
  5. Audit log (every message + blocked events)
"""

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_IDS = set(
    int(cid.strip())
    for cid in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if cid.strip()
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _is_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS


# Lazy singletons
_agent = None
_security = None


def get_agent():
    global _agent
    if _agent is None:
        from sdk_bridge.main_agent import MainAgent
        _agent = MainAgent()
    return _agent


def get_security():
    global _security
    if _security is None:
        from security.security import SecurityManager
        _security = SecurityManager()
    return _security


# ------------------------------------------------------------------
# Secure send — exfiltration guard on every outbound message
# ------------------------------------------------------------------

async def _secure_send(update: Update, text: str, chunk_size: int = 4000) -> None:
    """Scan for secrets then send. Splits long messages automatically."""
    from security.exfiltration_guard import scan

    clean, detected = scan(text)
    if detected:
        get_security().audit(
            "blocked",
            chat_id=str(update.effective_chat.id),
            detail=f"Exfiltration guard blocked: {detected}",
            blocked=True,
        )

    if len(clean) <= chunk_size:
        await update.message.reply_text(clean)
        return
    for i in range(0, len(clean), chunk_size):
        await update.message.reply_text(clean[i:i + chunk_size])


# ------------------------------------------------------------------
# Command handlers
# ------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("POLAR online. Session locked — send your PIN to unlock.")
        return
    await _secure_send(update, "POLAR online. How can I help?")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("Session locked.")
        return
    response = get_agent().receive(
        "Give me a brief status report of all active tasks and recent Hive Mind entries.",
        chat_id=str(chat_id),
    )
    await _secure_send(update, response)


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("Session locked.")
        return
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    pinned = hive.read_pinned()
    if not pinned:
        await update.message.reply_text("No pinned memories found.")
        return
    lines = ["*Pinned Memories*"]
    for m in pinned:
        lines.append(f"• `{m['key']}`: {m['value']}")
    await _secure_send(update, "\n".join(lines))


async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("Session locked.")
        return
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    projects = hive.list_projects(status="active")
    if not projects:
        await update.message.reply_text("No active projects.")
        return
    lines = ["*Active Projects*"]
    for p in projects:
        lines.append(f"• `{p['name']}` — {p['path']}")
    await _secure_send(update, "\n".join(lines))


async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually lock the session."""
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    get_security().lock(chat_id=str(chat_id))
    await update.message.reply_text("Session locked.")


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List scheduled tasks."""
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("Session locked.")
        return
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    tasks = hive.list_scheduled_tasks()
    if not tasks:
        await update.message.reply_text("No scheduled tasks. Add them from the Dashboard → Tasks tab.")
        return
    status_icon = {"active": "✅", "paused": "⏸", "running": "⚡", "error": "⚠️"}
    lines = ["*Scheduled Tasks*"]
    for t in tasks[:10]:
        icon    = status_icon.get(t["status"], "•")
        next_r  = (t.get("next_run") or "")[:16].replace("T", " ")
        prompt  = (t.get("prompt") or "")[:60]
        lines.append(f"{icon} `{t['schedule']}` — {prompt}\n  ↳ Next: {next_r}")
    await _secure_send(update, "\n\n".join(lines))


async def cmd_missions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List mission queue."""
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("Session locked.")
        return
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    missions = hive.list_missions(limit=10)
    if not missions:
        await update.message.reply_text("No missions in queue.")
        return
    status_icon = {"queued": "🕐", "running": "⚡", "completed": "✅", "failed": "❌", "cancelled": "🚫"}
    prio_label  = {1: "P1 Urgent", 2: "P2 High", 3: "P3 Normal", 4: "P4 Low", 5: "P5 Backlog"}
    lines = ["*Mission Queue*"]
    for m in missions:
        icon   = status_icon.get(m["status"], "•")
        prio   = prio_label.get(m.get("priority", 3), "P3")
        agent  = (m.get("assigned_agent") or "auto").replace("_agent", "")
        lines.append(f"{icon} [{prio}] *{m['title']}*\n  Agent: {agent} · Status: {m['status']}")
    await _secure_send(update, "\n\n".join(lines))


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent audit log entries."""
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        await update.message.reply_text("Access denied.")
        return
    sec = get_security()
    if sec.is_locked():
        await update.message.reply_text("Session locked.")
        return
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    entries = hive.get_audit_log(limit=10)
    if not entries:
        await update.message.reply_text("No audit entries yet.")
        return
    lines = ["*Recent Audit Log*"]
    for e in entries:
        ts = e["created_at"][:16].replace("T", " ")
        flag = " 🚫" if e["blocked"] else ""
        lines.append(f"`{ts}` *{e['action']}*{flag}\n  {(e['detail'] or '')[:80]}")
    await _secure_send(update, "\n\n".join(lines))


# ------------------------------------------------------------------
# Message handler
# ------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    str_chat_id = str(chat_id)

    # Layer 1: Chat ID allow-list
    if not _is_allowed(chat_id):
        logger.warning(f"Blocked unauthorized chat_id={chat_id}")
        await update.message.reply_text("Access denied.")
        return

    text = update.message.text or ""
    sec = get_security()

    # Layer 2: Kill phrase (must check before lock)
    if sec.check_kill_phrase(text, chat_id=str_chat_id):
        await update.message.reply_text("POLAR shutting down.")
        return

    # Layer 3: PIN lock
    if sec.is_locked():
        stripped = text.strip()
        if stripped.isdigit():
            if sec.unlock(stripped, chat_id=str_chat_id):
                await update.message.reply_text("Unlocked. How can I help?")
            else:
                await update.message.reply_text("Wrong PIN. Try again.")
        else:
            await update.message.reply_text(
                "Session locked. Send your PIN to unlock."
            )
        return

    logger.info(f"Message from {chat_id}: {text[:80]}")
    sec.audit("message", chat_id=str_chat_id, detail=text[:200])

    await update.message.reply_chat_action("typing")

    try:
        response = get_agent().receive(text, chat_id=str_chat_id)
    except Exception as e:
        logger.error(f"Main agent error: {e}")
        response = f"[SYSTEM ERROR] {e}"

    # Layer 4: Exfiltration guard + send
    await _secure_send(update, response)

    # Reset idle timer after successful interaction
    sec.reset_idle_timer()


# ------------------------------------------------------------------
# Bot runner
# ------------------------------------------------------------------

def run_bot() -> None:
    """Start the Telegram bot (blocking)."""
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("missions", cmd_missions))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("POLAR Telegram bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()
