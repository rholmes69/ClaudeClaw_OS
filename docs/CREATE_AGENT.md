# Creating a New Agent — ClaudeClaw OS

This guide covers three ways to add a new specialist agent to ClaudeClaw OS POLAR.

---

## Prerequisites

- Python 3.10+ with dependencies installed (`pip install -r requirements.txt`)
- A Telegram bot token for the new agent (create one at [@BotFather](https://t.me/BotFather))
- The project `.env` file present in the root directory

---

## Method 1 — Interactive Wizard (Recommended)

Run the creation wizard from the project root:

```bash
python scripts/create_agent.py
```

The wizard walks you through 6 steps:

| Step | Prompt | Example |
|---|---|---|
| 1 | Agent ID | `legal` |
| 2 | Display name | `Legal Agent` |
| 3 | Personality | `Contract and compliance specialist...` |
| 4 | Telegram bot token | `8123456789:AAF...` |
| 5 | Model | `1` (Sonnet) or `2` (Opus) |
| 6 | Domains | `contracts, compliance, NDAs` |

When confirmed, the wizard automatically:

- Creates `agents/legal/agent.yaml` with `version: "1.0.0"`
- Creates `agents/legal/CLAUDE.md` from the template
- Appends `LEGAL_TELEGRAM_TOKEN=<token>` to `.env`
- Creates `start_legal_bot.bat` launcher (Windows)
- Snapshots version `1.0.0` in the Hive Mind database

---

## Method 2 — Manual YAML

Create the agent directory and config file by hand.

**1. Create the directory:**
```bash
mkdir agents/legal
```

**2. Create `agents/legal/agent.yaml`:**
```yaml
id: legal
version: "1.0.0"
name: Legal Agent
model: claude-sonnet-4-6
personality: Contract and compliance specialist. Reviews NDAs, flags risk clauses, and tracks regulatory requirements.
color: "#f472b6"
telegram_token_env: LEGAL_TELEGRAM_TOKEN
domains:
  - contract review
  - compliance
  - NDA drafting
  - regulatory tracking
```

**3. Create `agents/legal/CLAUDE.md`** (copy from template and edit):
```bash
cp agents/_template/CLAUDE.md agents/legal/CLAUDE.md
```
Replace `{{AGENT_NAME}}` with `Legal Agent` and `{{PERSONALITY}}` with your personality string.

**4. Add the token to `.env`:**
```
LEGAL_TELEGRAM_TOKEN=<your_bot_token>
```

**5. Snapshot the initial version into the Hive Mind:**
```bash
python -c "
from sdk_bridge.orchestrator import register_agent
register_agent(
    agent_id='legal',
    name='Legal Agent',
    personality='Contract and compliance specialist.',
    telegram_token_env='LEGAL_TELEGRAM_TOKEN',
    domains=['contract review', 'compliance', 'NDA drafting'],
)
print('Done')
"
```

---

## Method 3 — Python API

Call `register_agent()` directly from code:

```python
from sdk_bridge.orchestrator import register_agent

cfg = register_agent(
    agent_id="legal",
    name="Legal Agent",
    personality="Contract and compliance specialist. Reviews NDAs and flags risk clauses.",
    telegram_token_env="LEGAL_TELEGRAM_TOKEN",
    model="claude-sonnet-4-6",           # or "claude-opus-4-6"
    domains=["contract review", "compliance", "NDA drafting"],
    color="#f472b6",                      # optional hex color for dashboard
)
print(cfg)
```

This writes the YAML, creates CLAUDE.md, and snapshots `v1.0.0` in the Hive Mind automatically.

---

## Wiring the Agent into the Router

After creating the YAML, register the agent class in the SDK bridge so it can receive delegated tasks.

**1. Create the agent class** at `agents/legal_agent.py`:

```python
import os
import anthropic

class LegalAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def receive(self, task: dict) -> dict:
        instruction = task.get("instruction", "")
        hive_context = task.get("hive_context", "")

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=(
                "You are the Legal Agent of ClaudeClaw OS POLAR. "
                "You specialise in contract review, compliance, and NDA drafting. "
                "Always respond in JSON: {response, summary, memory_entries}."
            ),
            messages=[{"role": "user", "content": instruction}],
        )

        text = response.content[0].text
        return {"response": text, "summary": "Legal task completed."}
```

**2. Add the agent to `sdk_bridge/router.py`:**

```python
AGENT_MAP = {
    "comms":    ("agents.comms_agent",   "CommsAgent"),
    "content":  ("agents.content_agent", "ContentAgent"),
    "ops":      ("agents.ops_agent",     "OpsAgent"),
    "research": ("agents.research_agent","ResearchAgent"),
    "finance":  ("agents.finance_agent", "FinanceAgent"),
    "legal":    ("agents.legal_agent",   "LegalAgent"),   # <-- add this line
}
```

**3. Add the routing target to `sdk_bridge/main_agent.py`:**

In the `ROUTING_TOOL` definition, add `"legal"` to the agent enum and describe its domains:

```python
# In the enum list:
"enum": ["comms", "content", "ops", "research", "finance", "legal"],

# In the descriptions:
"legal: contract review, compliance, NDA drafting, regulatory tracking."
```

---

## Starting the Agent's Bot

```bash
# From the project root:
python main.py --agent legal

# Or double-click the generated launcher (Windows):
start_legal_bot.bat
```

---

## Versioning

Every agent starts at `version: "1.0.0"`. When you update an agent's model, personality, or domains, bump the version to keep a history:

```python
from sdk_bridge.orchestrator import bump_agent_version

# patch — typo or wording fix
bump_agent_version("legal", bump_type="patch", changelog="Fixed typo in personality.")

# minor — new domain or capability
bump_agent_version("legal", bump_type="minor", changelog="Added GDPR compliance domain.")

# major — breaking change (model swap, full personality rewrite)
bump_agent_version("legal", bump_type="major", changelog="Upgraded to Opus 4. Full rewrite.")
```

To roll back to a previous version:

```python
from sdk_bridge.orchestrator import rollback_agent_version

rollback_agent_version("legal", "1.0.0")
```

To view an agent's full version history via the API:

```
GET /api/agents/legal/versions
GET /api/agents/legal/versions/active
```

---

## Agent YAML Reference

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique identifier — lowercase, letters/digits/hyphens, max 30 chars |
| `version` | Yes | Semver string e.g. `"1.0.0"` |
| `name` | Yes | Display name shown in dashboard and Telegram |
| `model` | Yes | `claude-sonnet-4-6` or `claude-opus-4-6` |
| `personality` | Yes | One-sentence role description (used in system prompt) |
| `color` | No | Hex color for dashboard avatar ring e.g. `"#f472b6"` |
| `telegram_token_env` | Yes | Environment variable name holding the bot token |
| `domains` | Yes | List of task domains this agent handles |

---

## Limits

- Maximum **20 agents** per ClaudeClaw OS instance.
- Agent IDs must be unique and match `^[a-z][a-z0-9_-]{0,29}$`.
- Each agent requires its own Telegram bot token and environment variable.


## AVATAR PROMPT Generations
Photorealistic portrait of a sharp, professional AI financial specialist named Angela. Cool teal and silver palette. Polished, authoritative expression. Subtle ledger or data grid pattern in background. Precise and trustworthy energy. Executive lighting. Square crop. add agent name: Angela -Finance Agent

Rewrite this prompt for new agent, Carl, the CI/CD Agent. Here is the reference prompt: "Photorealistic portrait of a sharp, professional AI financial specialist named Angela. Cool teal and silver palette. Polished, authoritative expression. Subtle ledger or data grid pattern in background. Precise and trustworthy energy. Executive lighting. Square crop. add agent name: Angela -Finance Agent"