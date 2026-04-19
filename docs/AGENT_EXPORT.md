# Agent Export & Packaging — ClaudeClaw OS

Agents can be exported from the dashboard as a self-contained ZIP package.
The package includes everything needed to reinstall the agent into another
ClaudeClaw OS instance.

---

## How to export

1. Open the dashboard and go to the **Agents** tab
2. Find the agent card you want to export
3. Click the **↓ Export** button at the bottom of the card
4. The browser downloads `{agent_id}_agent_package.zip` immediately

No confirmation step — the download starts straight away.

---

## What's inside the ZIP

```
{agent_id}_agent_package/
├── agent.yaml            # Agent configuration
├── CLAUDE.md             # Agent system prompt
├── {agent_id}_agent.py   # Python module (if it exists)
├── avatar.{ext}          # Avatar image: png, jpg, jpeg, or webp (if it exists)
├── manifest.json         # Export metadata + full version history
└── README.md             # Quick-start install instructions
```

### agent.yaml
The full agent config: id, version, name, model, personality, color,
telegram token env var, and domains list.

### CLAUDE.md
The agent's system prompt. This is what the agent reads at the start of
every session to understand its role, rules, and output format.

### {agent_id}_agent.py
The Python class that powers the agent — includes the tool definitions,
tool executors, system prompt, and `receive()` method. Only included if
the file exists at `agents/{agent_id}_agent.py`.

### avatar.{ext}
The avatar image displayed in the dashboard. Checked in order:
`png → jpg → jpeg → webp`. Only the first match is included.
If no avatar exists, this file is omitted from the package.

### manifest.json
Machine-readable metadata for the package:

```json
{
  "agent_id": "cicd",
  "name": "CI/CD Agent",
  "active_version": "1.0.0",
  "model": "claude-sonnet-4-6",
  "personality": "DevOps specialist...",
  "domains": ["git push", "git pull", "..."],
  "color": "#f97316",
  "exported_at": "2026-04-18T20:00:00Z",
  "version_history": [
    {
      "version": "1.0.0",
      "bump_type": "major",
      "changelog": "Initial version.",
      "model": "claude-sonnet-4-6",
      "is_active": true,
      "created_at": "2026-04-18T...",
      "created_by": "system"
    }
  ]
}
```

The `version_history` array contains every version snapshot ever recorded
in the Hive Mind for this agent — useful for auditing what changed between
versions before importing.

### README.md
Human-readable install instructions generated at export time, including
the active version and a step-by-step guide for wiring the agent into
the destination instance.

---

## Installing an exported package

### Step 1 — Copy the agent files

```bash
# Create the agent directory
mkdir agents/{agent_id}

# Copy config and system prompt
cp agent.yaml  agents/{agent_id}/agent.yaml
cp CLAUDE.md   agents/{agent_id}/CLAUDE.md

# Copy the Python module
cp {agent_id}_agent.py  agents/{agent_id}_agent.py

# Copy the avatar (if included)
cp avatar.png  dashboard/static/avatars/{agent_id}.png
```

### Step 2 — Add the bot token to .env

```bash
# Add to .env (replace with the actual token)
{AGENT_ID}_TELEGRAM_TOKEN=<your_bot_token>
```

Each agent needs its own Telegram bot token. Create one at [@BotFather](https://t.me/BotFather)
if you don't have one for this agent already.

### Step 3 — Register the agent in the router

Add one line to `sdk_bridge/router.py`:

```python
AGENT_MAP = {
    ...
    "{agent_id}": ("agents.{agent_id}_agent", "{ClassName}Agent"),
}
```

### Step 4 — Add to the routing enum

In `sdk_bridge/main_agent.py`, add the agent ID to the enum and describe its domains:

```python
"enum": [..., "{agent_id}"],

# In the description string:
"{agent_id}: brief description of what this agent handles."
```

### Step 5 — Snapshot the version in the Hive Mind

```python
from sdk_bridge.orchestrator import get_agent_config
from hive_mind.db import HiveMindDB

cfg = get_agent_config("{agent_id}")
HiveMindDB().snapshot_agent_version(
    agent_id="{agent_id}",
    version="1.0.0",
    model=cfg["model"],
    personality=cfg["personality"],
    domains=cfg.get("domains", []),
    changelog="Imported from package.",
    bump_type="major",
)
```

### Step 6 — Restart the bot

```bash
python main.py
```

The agent is now live and the dashboard will show it with the correct
avatar and version number.

---

## API reference

The export is available directly via the REST API without using the dashboard:

```
GET /api/agents/{agent_id}/export
```

Response: `application/zip` file download named `{agent_id}_agent_package.zip`.

Returns `404` with a JSON error if the agent ID is not found.

### Example — download via curl

```bash
curl -O http://localhost:5000/api/agents/cicd/export
# saves: cicd_agent_package.zip
```

---

## What is NOT included

| Item | Reason |
|---|---|
| `.env` values / tokens | Secrets are never exported — add them manually in the destination |
| Hive Mind memories | Session memories are instance-specific and not portable |
| Scheduled tasks | Task schedules are instance-specific |
| Launcher `.bat` files | Re-generate with `scripts/create_agent.py` or manually |

---

## Related

- [CREATE_AGENT.md](CREATE_AGENT.md) — Full agent creation guide
- [AGENT_LIMITS.md](AGENT_LIMITS.md) — Agent instance limits and scaling
- `GET /api/agents/{id}/versions` — Full version history API
- `POST /api/agents/{id}/versions/bump` — Bump agent version before exporting
