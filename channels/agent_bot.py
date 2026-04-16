"""Per-Agent Telegram Bot

Generic bot runner for specialist agents. Each agent gets their own
Telegram bot token and personality. Messages route directly to the
specific agent — no main-agent triage layer.

Security layers (same as main bot):
  1. Chat ID allow-list
  2. Kill phrase check
  3. PIN lock check
  4. Exfiltration guard on every outbound send

Usage:
    python main.py --agent comms
    python main.py --agent research
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


# Lazy singletons keyed by agent_id
_routers: dict = {}
_security = None


def _get_router():
    from sdk_bridge.router import AgentRouter
    return AgentRouter()


def _get_security():
    global _security
    if _security is None:
        from security.security import SecurityManager
        _security = SecurityManager()
    return _security


async def _secure_send(update: Update, text: str, chunk_size: int = 4000) -> None:
    from security.exfiltration_guard import scan
    from security.security import get_security
    clean, detected = scan(text)
    if detected:
        get_security().audit("blocked", detail=f"Exfiltration guard: {detected}")
    for i in range(0, len(clean), chunk_size):
        await update.message.reply_text(clean[i:i + chunk_size])


def _call_agent(agent_id: str, instruction: str, chat_id: str) -> str:
    """Call the specific specialist agent directly."""
    try:
        router = _get_router()
        from hive_mind.memory_controller import MemoryController
        mem = MemoryController()
        hive_context = mem.load_session_context(query=instruction, agent_id=agent_id)

        result = router.route(agent_id, {
            "instruction": instruction,
            "context_summary": "",
            "hive_context": hive_context,
        })

        response = result.get("response", "Task completed.")

        # Post to hive mind log
        from sdk_bridge.orchestrator import post_to_hive
        post_to_hive(agent_id, "complete", instruction[:120])

        # Fire-and-forget memory ingestion
        from hive_mind.memory_ingest import ingest_conversation
        ingest_conversation(
            messages=[{"role": "user", "content": instruction},
                       {"role": "assistant", "content": response}],
            agent_id=agent_id,
            chat_id=chat_id,
        )

        return response
    except Exception as e:
        logger.error(f"[AgentBot:{agent_id}] Error: {e}")
        return f"[ERROR] {e}"


def build_bot(agent_id: str) -> Application:
    """
    Build and return a python-telegram-bot Application for the given agent.
    The agent's Telegram token is read from the env var specified in agent.yaml.
    """
    from sdk_bridge.orchestrator import get_agent_config
    cfg = get_agent_config(agent_id)
    if not cfg:
        raise ValueError(f"No agent config found for '{agent_id}'")

    token_env = cfg.get("telegram_token_env", "")
    token = os.getenv(token_env, "")
    if not token:
        raise ValueError(
            f"Agent '{agent_id}' requires env var '{token_env}' but it is not set. "
            f"Add it to your .env file."
        )

    agent_name = cfg.get("name", agent_id)
    logger.info(f"[AgentBot] Building bot for '{agent_name}' using token env '{token_env}'")

    # ── Handlers ────────────────────────────────────────────────────────────

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update.effective_chat.id):
            await update.message.reply_text("Access denied.")
            return
        sec = _get_security()
        if sec.is_locked():
            await update.message.reply_text(f"{agent_name} online. Session locked — send your PIN.")
            return
        await _secure_send(update, f"{agent_name} online. How can I help?")

    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update.effective_chat.id):
            await update.message.reply_text("Access denied.")
            return
        sec = _get_security()
        if sec.is_locked():
            await update.message.reply_text("Session locked.")
            return
        domains = cfg.get("domains", [])
        domain_text = ", ".join(domains) if domains else "general"
        await _secure_send(update, f"*{agent_name}*\nDomains: {domain_text}\nModel: {cfg.get('model','claude-sonnet-4-6')}\nStatus: online")

    async def cmd_hive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show recent hive mind entries from this agent."""
        if not _is_allowed(update.effective_chat.id):
            await update.message.reply_text("Access denied.")
            return
        sec = _get_security()
        if sec.is_locked():
            await update.message.reply_text("Session locked.")
            return
        from sdk_bridge.orchestrator import get_hive_entries
        entries = get_hive_entries(limit=5, agent_id=agent_id)
        if not entries:
            await update.message.reply_text("No hive entries yet.")
            return
        lines = [f"*{agent_name} — Hive Log*"]
        for e in entries:
            ts = (e.get("created_at") or "")[:16].replace("T", " ")
            lines.append(f"`{ts}` *{e['action']}*\n{e['summary'][:100]}")
        await _secure_send(update, "\n\n".join(lines))

    async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed(update.effective_chat.id):
            await update.message.reply_text("Access denied.")
            return
        _get_security().lock(chat_id=str(update.effective_chat.id))
        await update.message.reply_text("Session locked.")

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        str_chat_id = str(chat_id)

        if not _is_allowed(chat_id):
            await update.message.reply_text("Access denied.")
            return

        text = update.message.text or ""
        sec = _get_security()

        # Kill phrase
        if sec.check_kill_phrase(text, chat_id=str_chat_id):
            await update.message.reply_text("POLAR shutting down.")
            return

        # PIN lock
        if sec.is_locked():
            stripped = text.strip()
            if stripped.isdigit():
                if sec.unlock(stripped, chat_id=str_chat_id):
                    await update.message.reply_text("Unlocked. How can I help?")
                else:
                    await update.message.reply_text("Wrong PIN.")
            else:
                await update.message.reply_text("Session locked. Send your PIN.")
            return

        logger.info(f"[AgentBot:{agent_id}] Message from {chat_id}: {text[:80]}")
        sec.audit("message", agent_id=agent_id, chat_id=str_chat_id, detail=text[:200])

        await update.message.reply_chat_action("typing")

        response = _call_agent(agent_id, text, str_chat_id)
        await _secure_send(update, response)
        sec.reset_idle_timer()

    # ── Build application ────────────────────────────────────────────────────

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("hive", cmd_hive))
    application.add_handler(CommandHandler("lock", cmd_lock))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return application


def run_agent_bot(agent_id: str) -> None:
    """Start the Telegram bot for the given agent (blocking)."""
    application = build_bot(agent_id)
    logger.info(f"[AgentBot] Starting bot for '{agent_id}'...")
    application.run_polling(drop_pending_updates=True)
