"""Agent Creation Wizard

Interactive CLI for creating a new ClaudeClaw specialist agent.
Run from the ClaudeClaw_OS root directory:

    python scripts/create_agent.py

Steps:
  1. Enter agent ID (validated: lowercase, letters/digits/hyphens, max 30 chars)
  2. Enter display name
  3. Enter personality / role description
  4. Paste Telegram bot token (validated against Telegram API)
  5. Choose model (default: claude-sonnet-4-6)
  6. Enter domains (comma-separated)
  7. Writes agents/{id}/agent.yaml and agents/{id}/CLAUDE.md
  8. Appends {ID}_TELEGRAM_TOKEN to .env
  9. Generates a Windows .bat launcher for this agent
"""

import os
import re
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()


def _validate_token(token: str) -> bool:
    """Check the token against Telegram API."""
    try:
        import urllib.request, json
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
            if data.get("ok"):
                username = data.get("result", {}).get("username", "")
                print(f"  ✓ Token valid — bot username: @{username}")
                return True
    except Exception as e:
        print(f"  ✗ Token validation failed: {e}")
    return False


def _append_to_env(env_var: str, token: str) -> None:
    env_path = ROOT / ".env"
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if env_var in content:
        print(f"  ℹ  {env_var} already exists in .env — skipping.")
        return
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\n# Agent: {env_var}\n{env_var}={token}\n")
    print(f"  ✓ Added {env_var} to .env")


def _write_bat_launcher(agent_id: str) -> None:
    bat_path = ROOT / f"start_{agent_id}_bot.bat"
    bat_content = (
        f"@echo off\n"
        f"cd /d \"%~dp0\"\n"
        f"echo Starting {agent_id} agent bot...\n"
        f"python main.py --agent {agent_id}\n"
        f"pause\n"
    )
    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"  ✓ Created launcher: start_{agent_id}_bot.bat")


def main():
    print("=" * 50)
    print("  ClaudeClaw OS — Agent Creation Wizard")
    print("=" * 50)
    print()

    from sdk_bridge.orchestrator import load_registry, validate_agent_id, register_agent, MAX_AGENTS

    registry = load_registry()
    print(f"  Registered agents: {len(registry)}/{MAX_AGENTS}")
    if registry:
        print(f"  Existing: {', '.join(sorted(registry.keys()))}")
    print()

    if len(registry) >= MAX_AGENTS:
        print(f"  ✗ Maximum of {MAX_AGENTS} agents reached.")
        sys.exit(1)

    # ── Step 1: Agent ID ────────────────────────────────────────────────────
    while True:
        agent_id = input("Agent ID (lowercase, e.g. 'finance'): ").strip().lower()
        if not validate_agent_id(agent_id):
            print("  ✗ Invalid ID. Use lowercase letters, digits, hyphens. Max 30 chars. Must start with a letter.")
            continue
        if agent_id in registry:
            print(f"  ✗ Agent '{agent_id}' already exists.")
            continue
        break

    # ── Step 2: Display name ────────────────────────────────────────────────
    name = input(f"Display name (e.g. 'Finance Agent'): ").strip()
    if not name:
        name = agent_id.capitalize() + " Agent"

    # ── Step 3: Personality ─────────────────────────────────────────────────
    print("Personality / role description (one sentence):")
    personality = input("> ").strip()
    if not personality:
        personality = f"A specialized ClaudeClaw agent."

    # ── Step 4: Telegram token ──────────────────────────────────────────────
    env_var = f"{agent_id.upper().replace('-','_')}_TELEGRAM_TOKEN"
    print(f"\nTelegram bot token for this agent.")
    print(f"  Will be stored as: {env_var}")
    print(f"  Create a new bot at @BotFather if you haven't already.")
    while True:
        token = input("Bot token: ").strip()
        if not token:
            print("  ✗ Token cannot be empty.")
            continue
        print("  Validating token against Telegram API...")
        if _validate_token(token):
            break
        retry = input("  Try again? (y/n): ").strip().lower()
        if retry != "y":
            print("  Skipping token validation. You can add it to .env manually.")
            break

    # ── Step 5: Model ───────────────────────────────────────────────────────
    print("\nModel to use:")
    print("  1. claude-sonnet-4-6 (default, fast, cost-effective)")
    print("  2. claude-opus-4-6   (more capable, slower)")
    model_choice = input("Choice [1]: ").strip()
    model = "claude-opus-4-6" if model_choice == "2" else "claude-sonnet-4-6"

    # ── Step 6: Domains ─────────────────────────────────────────────────────
    print("\nDomains this agent handles (comma-separated, e.g. 'invoices, expenses, payroll'):")
    domains_raw = input("> ").strip()
    domains = [d.strip() for d in domains_raw.split(",") if d.strip()]

    # ── Summary ─────────────────────────────────────────────────────────────
    print()
    print("─" * 40)
    print(f"  ID:          {agent_id}")
    print(f"  Name:        {name}")
    print(f"  Model:       {model}")
    print(f"  Personality: {personality[:60]}...")
    print(f"  Domains:     {', '.join(domains) or '(none)'}")
    print(f"  Token env:   {env_var}")
    print("─" * 40)
    confirm = input("\nCreate this agent? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    # ── Create ───────────────────────────────────────────────────────────────
    print()
    cfg = register_agent(
        agent_id=agent_id,
        name=name,
        personality=personality,
        telegram_token_env=env_var,
        model=model,
        domains=domains,
    )
    print(f"  ✓ Created agents/{agent_id}/agent.yaml")
    print(f"  ✓ Created agents/{agent_id}/CLAUDE.md")

    if token:
        _append_to_env(env_var, token)

    _write_bat_launcher(agent_id)

    print()
    print("=" * 50)
    print(f"  Agent '{name}' created successfully!")
    print()
    print(f"  To start this agent's bot, run:")
    print(f"    python main.py --agent {agent_id}")
    print(f"  Or double-click: start_{agent_id}_bot.bat")
    print()
    print(f"  Users can message it directly on Telegram, or")
    print(f"  use '@{agent_id}: task' in the main POLAR bot.")
    print("=" * 50)


if __name__ == "__main__":
    main()
