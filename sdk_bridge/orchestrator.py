"""SDK Bridge — Agent Orchestrator

Manages the multi-agent registry. Reads agent YAML configs from agents/{id}/agent.yaml,
exposes lifecycle operations, handles inter-agent delegation, and coordinates the
shared Hive Mind log.

Delegation syntax (recognised in Telegram messages to the main bot):
    @research: find me info about X
    @comms: draft an email to Sarah
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent / "agents"
MAX_AGENTS = 20

# 15-color palette (cycles if > 15 agents)
_COLOR_PALETTE = [
    "#60a5fa", "#4ade80", "#fbbf24", "#c084fc", "#f472b6",
    "#34d399", "#f87171", "#a78bfa", "#fb923c", "#38bdf8",
    "#86efac", "#fcd34d", "#e879f9", "#67e8f9", "#d9f99d",
]

# Agent ID validation pattern (lowercase, starts with letter, max 30 chars)
_ID_RE = re.compile(r'^[a-z][a-z0-9_-]{0,29}$')

# Delegation pattern: @agent_id: task text
_DELEGATION_RE = re.compile(r'^@([a-z][a-z0-9_-]{0,29})\s*:\s*(.+)$', re.DOTALL)


# ─────────────────────────────────────────────────────────────────────────────
# Registry helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback minimal YAML parser for simple key: value files
        result = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and ":" in line:
                    k, _, v = line.partition(":")
                    result[k.strip()] = v.strip().strip('"\'')
        return result
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}")
        return {}


def load_registry() -> dict[str, dict]:
    """
    Scan agents/ directory and load all agent.yaml configs.
    Returns dict keyed by agent ID.
    """
    registry = {}
    if not AGENTS_DIR.exists():
        return registry

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if agent_dir.name.startswith("_") or not agent_dir.is_dir():
            continue
        yaml_path = agent_dir / "agent.yaml"
        if not yaml_path.exists():
            continue
        cfg = _load_yaml(yaml_path)
        agent_id = cfg.get("id") or agent_dir.name
        if not _ID_RE.match(agent_id):
            logger.warning(f"Skipping agent with invalid ID: '{agent_id}'")
            continue
        cfg["id"] = agent_id
        cfg["config_path"] = str(yaml_path)
        registry[agent_id] = cfg

    return registry


def get_agent_config(agent_id: str) -> Optional[dict]:
    return load_registry().get(agent_id)


def list_agents() -> list[dict]:
    """Return all registered agents sorted by ID, with color assigned."""
    registry = load_registry()
    agents = []
    for i, (aid, cfg) in enumerate(sorted(registry.items())):
        entry = dict(cfg)
        if not entry.get("color"):
            entry["color"] = _COLOR_PALETTE[i % len(_COLOR_PALETTE)]
        # Resolve telegram token (mask for display)
        token_env = entry.get("telegram_token_env", "")
        token_val = os.getenv(token_env, "") if token_env else ""
        entry["has_token"] = bool(token_val)
        entry["token_env"] = token_env
        agents.append(entry)
    return agents


def assign_color(agent_id: str) -> str:
    agents = list_agents()
    ids = [a["id"] for a in agents]
    idx = ids.index(agent_id) if agent_id in ids else 0
    return _COLOR_PALETTE[idx % len(_COLOR_PALETTE)]


# ─────────────────────────────────────────────────────────────────────────────
# Delegation syntax
# ─────────────────────────────────────────────────────────────────────────────

def parse_delegation(text: str) -> Optional[tuple[str, str]]:
    """
    If text matches '@agent_id: task', return (agent_id, task).
    Otherwise return None.
    """
    m = _DELEGATION_RE.match(text.strip())
    if not m:
        return None
    agent_id = m.group(1)
    task = m.group(2).strip()
    registry = load_registry()
    if agent_id not in registry:
        return None
    return agent_id, task


# ─────────────────────────────────────────────────────────────────────────────
# Hive Mind coordination
# ─────────────────────────────────────────────────────────────────────────────

def post_to_hive(
    agent_id: str,
    action: str,
    summary: str,
    artifacts: Optional[dict] = None,
    tags: Optional[list] = None,
) -> str:
    """Write an entry to the shared Hive Mind log."""
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    return hive.hive_post(
        agent_id=agent_id,
        action=action,
        summary=summary,
        artifacts=artifacts,
        tags=tags,
    )


def get_hive_entries(limit: int = 20, agent_id: Optional[str] = None) -> list[dict]:
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()
    return hive.hive_get(limit=limit, agent_id=agent_id)


# ─────────────────────────────────────────────────────────────────────────────
# Agent lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def validate_agent_id(agent_id: str) -> bool:
    return bool(_ID_RE.match(agent_id))


def register_agent(
    agent_id: str,
    name: str,
    personality: str,
    telegram_token_env: str,
    model: str = "claude-sonnet-4-6",
    color: Optional[str] = None,
    domains: Optional[list] = None,
) -> dict:
    """
    Write a new agent.yaml to agents/{id}/agent.yaml.
    Returns the config dict.
    """
    if not validate_agent_id(agent_id):
        raise ValueError(f"Invalid agent ID '{agent_id}'. Use lowercase letters, digits, hyphens. Max 30 chars.")

    registry = load_registry()
    if len(registry) >= MAX_AGENTS:
        raise ValueError(f"Maximum of {MAX_AGENTS} agents reached.")

    agent_dir = AGENTS_DIR / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)

    cfg = {
        "id": agent_id,
        "name": name,
        "model": model,
        "personality": personality,
        "color": color or _COLOR_PALETTE[len(registry) % len(_COLOR_PALETTE)],
        "telegram_token_env": telegram_token_env,
        "domains": domains or [],
    }

    yaml_path = agent_dir / "agent.yaml"
    # Write proper YAML (lists as block sequences)
    lines = []
    for k, v in cfg.items():
        if isinstance(v, list):
            lines.append(f"{k}:\n")
            for item in v:
                lines.append(f"  - {item}\n")
        else:
            # Quote values that contain special YAML characters
            val = str(v)
            if any(c in val for c in [':', '#', '[', ']', '{', '}']):
                val = f'"{val}"'
            lines.append(f"{k}: {val}\n")
    yaml_path.write_text("".join(lines), encoding="utf-8")

    # Write CLAUDE.md from template
    template_path = AGENTS_DIR / "_template" / "CLAUDE.md"
    claude_md_path = agent_dir / "CLAUDE.md"
    if template_path.exists() and not claude_md_path.exists():
        content = template_path.read_text(encoding="utf-8")
        content = content.replace("{{AGENT_NAME}}", name)
        content = content.replace("{{PERSONALITY}}", personality)
        claude_md_path.write_text(content, encoding="utf-8")

    logger.info(f"[Orchestrator] Registered agent '{agent_id}' at {yaml_path}")

    # Snapshot initial version in the Hive Mind
    try:
        from hive_mind.db import HiveMindDB
        hive = HiveMindDB()
        hive.snapshot_agent_version(
            agent_id=agent_id,
            version="1.0.0",
            model=model,
            personality=personality,
            domains=domains or [],
            color=cfg.get("color"),
            changelog="Initial version.",
            bump_type="major",
            created_by="system",
        )
    except Exception as e:
        logger.warning(f"[Orchestrator] Could not snapshot version for '{agent_id}': {e}")

    return cfg


def bump_agent_version(
    agent_id: str,
    bump_type: str = "minor",
    changelog: Optional[str] = None,
    created_by: str = "system",
) -> str:
    """
    Read the current agent.yaml, compute the next semver, write a new version
    snapshot to the Hive Mind, and persist the new version string back to
    agent.yaml. Returns the new version string.

    bump_type:
        major — breaking change (personality overhaul, model swap)
        minor — new domain or capability added
        patch — typo fix, wording tweak
    """
    cfg = get_agent_config(agent_id)
    if not cfg:
        raise ValueError(f"Agent '{agent_id}' not found.")

    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()

    active = hive.get_active_version(agent_id)
    current_ver = active["version"] if active else cfg.get("version", "1.0.0")

    # Parse and bump semver
    try:
        parts = [int(x) for x in current_ver.split(".")]
        if len(parts) != 3:
            raise ValueError
    except ValueError:
        parts = [1, 0, 0]

    major, minor, patch = parts
    if bump_type == "major":
        major += 1; minor = 0; patch = 0
    elif bump_type == "minor":
        minor += 1; patch = 0
    else:
        patch += 1

    new_version = f"{major}.{minor}.{patch}"

    hive.snapshot_agent_version(
        agent_id=agent_id,
        version=new_version,
        model=cfg.get("model", "claude-sonnet-4-6"),
        personality=cfg.get("personality", ""),
        domains=cfg.get("domains", []),
        color=cfg.get("color"),
        changelog=changelog,
        bump_type=bump_type,
        created_by=created_by,
    )

    # Write new version back into agent.yaml
    yaml_path = Path(cfg["config_path"])
    text = yaml_path.read_text(encoding="utf-8")
    import re as _re
    if _re.search(r'^version:', text, _re.MULTILINE):
        text = _re.sub(r'^version:.*$', f'version: {new_version}', text, flags=_re.MULTILINE)
    else:
        text = f"version: {new_version}\n" + text
    yaml_path.write_text(text, encoding="utf-8")

    logger.info(f"[Orchestrator] Bumped '{agent_id}' {current_ver} → {new_version} ({bump_type})")
    return new_version


def rollback_agent_version(agent_id: str, version: str) -> dict:
    """
    Restore an agent's config from a past version snapshot.
    Rewrites agent.yaml with the snapshot values and marks that version active.
    Returns the restored config dict.
    """
    from hive_mind.db import HiveMindDB
    hive = HiveMindDB()

    snap = hive.get_version(agent_id, version)
    if not snap:
        raise ValueError(f"Version '{version}' not found for agent '{agent_id}'.")

    cfg = get_agent_config(agent_id)
    if not cfg:
        raise ValueError(f"Agent '{agent_id}' not found.")

    import json as _json
    domains = _json.loads(snap["domains"]) if isinstance(snap["domains"], str) else snap["domains"]

    yaml_path = Path(cfg["config_path"])
    lines = [
        f"id: {agent_id}\n",
        f"name: {cfg.get('name', agent_id)}\n",
        f"version: {version}\n",
        f"model: {snap['model']}\n",
    ]
    personality = snap["personality"]
    if any(c in personality for c in [':', '#', '[', ']', '{', '}']):
        personality = f'"{personality}"'
    lines.append(f"personality: {personality}\n")
    if snap.get("color"):
        lines.append(f'color: "{snap["color"]}"\n')
    token_env = cfg.get("telegram_token_env", "")
    lines.append(f"telegram_token_env: {token_env}\n")
    if domains:
        lines.append("domains:\n")
        for d in domains:
            lines.append(f"  - {d}\n")
    yaml_path.write_text("".join(lines), encoding="utf-8")

    hive.activate_version(agent_id, version)
    logger.info(f"[Orchestrator] Rolled back '{agent_id}' to {version}")

    return {
        "id": agent_id,
        "version": version,
        "model": snap["model"],
        "personality": snap["personality"],
        "domains": domains,
        "color": snap.get("color"),
    }
