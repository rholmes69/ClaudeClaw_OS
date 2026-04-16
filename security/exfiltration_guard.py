"""Security — Exfiltration Guard

Scans every outbound message for leaked API keys and secrets
before it reaches Telegram. Redacts matches with [REDACTED].

Patterns covered (15+):
  - Anthropic API keys (sk-ant-)
  - Generic SK keys
  - OpenAI keys
  - Google API keys (AIza)
  - Slack tokens (xoxb-, xoxp-)
  - GitHub tokens (ghp_, gho_)
  - AWS access keys (AKIA)
  - Stripe live/test keys
  - Twilio keys
  - SendGrid keys
  - Mailgun keys
  - Firebase server keys
  - Telegram bot tokens
  - Private key blocks (PEM)
  - Long hex strings (41+ chars)

Also scans for base64 and URL-encoded variants of actual
env var values marked as secrets.
"""

import base64
import logging
import os
import re
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ── Static regex patterns ─────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic_key",   re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}")),
    ("openai_key",      re.compile(r"sk-[a-zA-Z0-9]{32,}")),
    ("generic_sk",      re.compile(r"sk-[a-zA-Z0-9_\-]{20,}")),
    ("google_api_key",  re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("slack_bot",       re.compile(r"xoxb-[a-zA-Z0-9\-]+")),
    ("slack_user",      re.compile(r"xoxp-[a-zA-Z0-9\-]+")),
    ("github_pat",      re.compile(r"gh[po]_[a-zA-Z0-9]{20,}")),
    ("aws_access_key",  re.compile(r"AKIA[0-9A-Z]{16}")),
    ("stripe_live",     re.compile(r"sk_live_[a-zA-Z0-9]{24,}")),
    ("stripe_test",     re.compile(r"sk_test_[a-zA-Z0-9]{24,}")),
    ("twilio",          re.compile(r"SK[0-9a-fA-F]{32}")),
    ("sendgrid",        re.compile(r"SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}")),
    ("mailgun",         re.compile(r"key-[a-zA-Z0-9]{32}")),
    ("firebase",        re.compile(r"AAAA[a-zA-Z0-9_\-]{7}:[a-zA-Z0-9_\-]{140,}")),
    ("telegram_token",  re.compile(r"[0-9]{8,10}:[a-zA-Z0-9_\-]{35}")),
    ("private_key_pem", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA )?PRIVATE KEY-----"
    )),
    ("long_hex",        re.compile(r"(?<![a-fA-F0-9])[0-9a-fA-F]{41,}(?![a-fA-F0-9])")),
]

# Env var name fragments that indicate a secret
_SECRET_ENV_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "HASH")


def _get_env_secrets() -> list[tuple[str, str]]:
    """
    Return (name, value) pairs for env vars that look like secrets.
    Only values > 8 chars are checked.
    """
    results = []
    for name, value in os.environ.items():
        if any(frag in name.upper() for frag in _SECRET_ENV_FRAGMENTS):
            if value and len(value) > 8:
                results.append((name, value))
    return results


def scan(text: str) -> tuple[str, list[str]]:
    """
    Scan outbound text for secrets and redact them.

    Returns:
        (clean_text, list_of_detected_pattern_names)
    """
    detected: list[str] = []
    clean = text

    # ── Static pattern scan ──────────────────────────────────────
    for name, pattern in _PATTERNS:
        new_text, count = pattern.subn("[REDACTED]", clean)
        if count:
            detected.append(name)
            clean = new_text

    # ── Env var value scan (plain, base64, URL-encoded) ──────────
    for env_name, env_value in _get_env_secrets():
        variants = {
            "plain":   env_value,
            "base64":  base64.b64encode(env_value.encode()).decode(),
            "url":     quote(env_value, safe=""),
        }
        for variant_name, variant_value in variants.items():
            if variant_value in clean:
                clean = clean.replace(variant_value, "[REDACTED]")
                detected.append(f"env:{env_name}:{variant_name}")

    if detected:
        logger.warning(
            f"Exfiltration guard: blocked {len(detected)} secret(s): {detected}"
        )

    return clean, detected


def is_clean(text: str) -> bool:
    """Quick check — returns True if no secrets detected."""
    _, detected = scan(text)
    return len(detected) == 0
