"""Security — PIN lock, idle auto-lock, kill phrase, audit logging.

All four layers in one file (~215 lines, adapted from ClaudeClaw Power Pack 5).

Usage:
    from security.security import SecurityManager
    sec = SecurityManager()

    # In message handler (before processing):
    if sec.check_kill_phrase(text):
        return   # shutdown in progress

    if sec.is_locked():
        if text.strip().isdigit():
            if sec.unlock(text.strip(), chat_id=chat_id):
                await reply("Unlocked.")
            else:
                await reply("Wrong PIN.")
        else:
            await reply("Session locked. Send your PIN to unlock.")
        return

    # After processing:
    sec.reset_idle_timer()
    sec.audit("message", chat_id=chat_id, detail=text[:200])
"""

import hashlib
import logging
import os
import secrets
import signal
import sys
import threading
from typing import Optional

from dotenv import load_dotenv

from hive_mind.db import HiveMindDB

load_dotenv()

logger = logging.getLogger(__name__)

_IDLE_LOCK_MINUTES = int(os.getenv("IDLE_LOCK_MINUTES", "30"))
_PIN_HASH = os.getenv("SECURITY_PIN_HASH", "")
_KILL_PHRASE = os.getenv("EMERGENCY_KILL_PHRASE", "").strip().lower()


# ──────────────────────────────────────────────────────────────────────────────
# PIN utilities (module-level, no class needed)
# ──────────────────────────────────────────────────────────────────────────────

def generate_pin_hash(pin: str) -> str:
    """
    Generate a storable salt:hash for a PIN.
    Store the output in SECURITY_PIN_HASH in your .env.

    Example:
        python -c "from security.security import generate_pin_hash; print(generate_pin_hash('1234'))"
    """
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + pin).encode()).hexdigest()
    return f"{salt}:{h}"


def verify_pin(input_pin: str, stored_hash: str) -> bool:
    """Verify a raw PIN against a stored salt:hash string."""
    parts = stored_hash.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    actual = hashlib.sha256((salt + input_pin).encode()).hexdigest()
    return secrets.compare_digest(actual, expected)


# ──────────────────────────────────────────────────────────────────────────────
# SecurityManager
# ──────────────────────────────────────────────────────────────────────────────

class SecurityManager:
    """
    Manages session security for a POLAR bot instance.
    Thread-safe. One instance per bot process.
    """

    def __init__(self):
        self._hive = HiveMindDB()
        # Lock by default if a PIN hash is configured
        self._locked: bool = bool(_PIN_HASH)
        self._idle_timer: Optional[threading.Timer] = None
        if self._locked:
            logger.info("Security: PIN lock active. Session starts locked.")
        else:
            logger.info("Security: No PIN configured. Session unlocked.")

    # ── Lock state ──────────────────────────────────────────────

    def is_locked(self) -> bool:
        return self._locked

    def unlock(self, pin: str, chat_id: Optional[str] = None) -> bool:
        """
        Attempt to unlock with a PIN.
        Returns True on success, False on wrong PIN.
        """
        if not _PIN_HASH:
            self._locked = False
            return True

        if verify_pin(pin, _PIN_HASH):
            self._locked = False
            self.reset_idle_timer()
            self._hive.audit("unlock", chat_id=chat_id, detail="PIN accepted")
            logger.info(f"Security: session unlocked (chat_id={chat_id})")
            return True

        self._hive.audit("denied", chat_id=chat_id, detail="Wrong PIN attempt", blocked=True)
        logger.warning(f"Security: wrong PIN from chat_id={chat_id}")
        return False

    def lock(self, chat_id: Optional[str] = None) -> None:
        """Lock the session."""
        self._locked = True
        self._cancel_idle_timer()
        self._hive.audit("lock", chat_id=chat_id, detail="Session locked")
        logger.info("Security: session locked.")

    # ── Idle timer ───────────────────────────────────────────────

    def reset_idle_timer(self) -> None:
        """Reset the idle auto-lock countdown. Call after every successful interaction."""
        if not _PIN_HASH:
            return
        self._cancel_idle_timer()
        self._idle_timer = threading.Timer(
            _IDLE_LOCK_MINUTES * 60,
            self._on_idle_timeout,
        )
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _on_idle_timeout(self) -> None:
        logger.info(f"Security: idle timeout after {_IDLE_LOCK_MINUTES}m — locking session.")
        self.lock()

    # ── Kill phrase ──────────────────────────────────────────────

    def check_kill_phrase(self, text: str, chat_id: Optional[str] = None) -> bool:
        """
        Check if text matches the emergency kill phrase (case-insensitive exact match).
        If matched: logs to audit, sends SIGTERM to self, exits.
        Returns True if kill phrase detected (caller should abort further processing).
        """
        if not _KILL_PHRASE:
            return False
        if text.strip().lower() == _KILL_PHRASE:
            self._hive.audit(
                "kill",
                chat_id=chat_id,
                detail="Emergency kill phrase received — shutting down.",
            )
            logger.critical("Security: KILL PHRASE received. Shutting down POLAR.")
            # Give the audit write a moment to flush
            threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
            return True
        return False

    # ── Audit ────────────────────────────────────────────────────

    def audit(
        self,
        action: str,
        agent_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        detail: Optional[str] = None,
        blocked: bool = False,
    ) -> None:
        """Write an audit log entry."""
        try:
            self._hive.audit(
                action=action,
                agent_id=agent_id,
                chat_id=chat_id,
                detail=detail,
                blocked=blocked,
            )
        except Exception as e:
            logger.error(f"Audit log write failed: {e}")
