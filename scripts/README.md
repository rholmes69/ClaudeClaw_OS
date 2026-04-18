# scripts/create_agent.py

Interactive wizard for adding a new specialist agent to ClaudeClaw OS POLAR.

---

## Usage

Run from the project root:

```bash
python scripts/create_agent.py
```

---

## What it does

Walks you through 6 prompts, shows a confirmation summary, then writes all required files on confirmation.

---

## Step-by-step

### Step 1 — Agent ID

```
Agent ID (lowercase, e.g. 'finance'):
```

- Lowercase letters, digits, and hyphens only
- Must start with a letter
- Max 30 characters
- Must be unique — the wizard rejects an ID that already exists
- Examples: `legal`, `hr`, `social-media`

---

### Step 2 — Display name

```
Display name (e.g. 'Finance Agent'):
```

The name shown in the dashboard and in Telegram responses. If left blank, defaults to `{Id} Agent`.

---

### Step 3 — Personality

```
Personality / role description (one sentence):
```

One sentence describing what this agent does. This is injected directly into the agent's system prompt.

- Good: `Contract and compliance specialist. Reviews NDAs and flags risk clauses.`
- Avoid vague descriptions like `A helpful agent.`

---

### Step 4 — Telegram bot token

```
Bot token:
```

The token for this agent's dedicated Telegram bot.

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the token BotFather gives you and paste it here

The wizard validates the token live against the Telegram API. If validation fails you can retry or skip (and add the token to `.env` manually later).

---

### Step 5 — Model

```
1. claude-sonnet-4-6 (default, fast, cost-effective)
2. claude-opus-4-6   (more capable, slower)
Choice [1]:
```

Press Enter to accept the default (Sonnet). Type `2` for Opus.

Use Opus for agents that handle complex multi-step reasoning (e.g. deep research, legal analysis). Use Sonnet for everything else.

---

### Step 6 — Domains

```
Domains this agent handles (comma-separated):
```

A list of task types this agent is responsible for. The Main Agent uses these to decide when to route to this agent.

- Example: `contracts, compliance, NDA drafting, regulatory tracking`

---

## Confirmation summary

Before writing any files the wizard prints a summary:

```
----------------------------------------
  ID:          legal
  Name:        Legal Agent
  Version:     1.0.0
  Model:       claude-sonnet-4-6
  Personality: Contract and compliance specialist...
  Domains:     contracts, compliance, NDA drafting
  Token env:   LEGAL_TELEGRAM_TOKEN
----------------------------------------

Create this agent? (y/n):
```

Type `y` to confirm or `n` to abort without writing anything.

---

## Files created

| File | Description |
|---|---|
| `agents/{id}/agent.yaml` | Agent config — id, version, model, personality, domains |
| `agents/{id}/CLAUDE.md` | Agent system prompt, generated from template |
| `.env` | Bot token appended as `{ID}_TELEGRAM_TOKEN=<token>` |
| `start_{id}_bot.bat` | Windows launcher — double-click to start this agent's bot |

A `v1.0.0` snapshot is also written to the Hive Mind database automatically.

---

## After running the wizard

The wizard creates the config files but does **not** wire the agent into the routing layer. You need to do three more things manually:

### 1. Create the agent class

Create `agents/{id}_agent.py`:

```python
import os
import anthropic

class LegalAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def receive(self, task: dict) -> dict:
        instruction = task.get("instruction", "")
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system="You are the Legal Agent of ClaudeClaw OS POLAR...",
            messages=[{"role": "user", "content": instruction}],
        )
        return {
            "response": response.content[0].text,
            "summary": "Legal task completed.",
        }
```

### 2. Register in the router

Add one line to `sdk_bridge/router.py`:

```python
AGENT_MAP = {
    ...
    "legal": ("agents.legal_agent", "LegalAgent"),   # add this
}
```

### 3. Add to the routing enum

In `sdk_bridge/main_agent.py`, find the `ROUTING_TOOL` definition and add the new agent ID to the enum and its description:

```python
# enum list:
"enum": ["comms", "content", "ops", "research", "finance", "legal"],

# description:
"legal: contract review, compliance, NDA drafting, regulatory tracking."
```

---

## Adding a dashboard avatar

The dashboard displays an avatar image for each agent. Without one, the agent card shows a colored placeholder ring using the `color` from `agent.yaml`.

### How it works

The dashboard looks for an image file at:

```
dashboard/static/avatars/{agent_id}.{ext}
```

Supported formats: `png`, `jpg`, `jpeg`, `webp` — checked in that order. The first match is used.

For a `legal` agent, place the image at:

```
dashboard/static/avatars/legal.png
```

No code change or restart is required — the dashboard picks it up on the next page load.

---

### Image requirements

| Property | Recommendation |
|---|---|
| Format | PNG (transparent background) or JPG |
| Dimensions | Square — at least **256 × 256 px** |
| Aspect ratio | 1:1 (square) — non-square images will appear cropped |
| File size | Under 2 MB |
| Style | Consistent with the other agents (portrait, illustrated, or AI-generated) |

---

### Creating an avatar

**Option A — AI image generator (recommended)**

Use any image generator with a prompt like:

```
Portrait of a professional AI legal assistant, digital art style,
square format, clean background, consistent with a tech dashboard UI.
```

Tools that work well: ChatGPT (DALL-E), Midjourney, Adobe Firefly, Leonardo.ai.

**Option B — Use an existing image**

Resize any square image to at least 256 × 256 px and save it as `{agent_id}.png`.

Free resize tools: [squoosh.app](https://squoosh.app), Preview (Mac), Paint (Windows).

**Option C — Match the existing agent style**

The current avatars in `dashboard/static/avatars/` (comms, content, finance, main, ops, research) use a consistent AI-illustrated portrait style. To keep the dashboard uniform, generate an image in the same style.

---

### Placing the file

```bash
# Copy your image into the avatars directory
cp ~/Downloads/legal-avatar.png dashboard/static/avatars/legal.png
```

Reload the dashboard in your browser — the avatar appears immediately.

---

### Fallback behavior

If no image file is found, the dashboard uses the agent's `color` value from `agent.yaml` as a colored ring placeholder. The agent still works normally — the avatar is cosmetic only.

To change the fallback color, edit the `color` field in `agents/{id}/agent.yaml`:

```yaml
color: "#f472b6"
```

Then bump the version to record the change:

```bash
python -c "from sdk_bridge.orchestrator import bump_agent_version; bump_agent_version('legal', 'patch', 'Updated color.')"
```

---

## Starting the agent's bot

```bash
# CLI
python main.py --agent legal

# Windows — double-click the generated launcher
start_legal_bot.bat
```

---

## Limits

- Maximum **20 agents** per instance
- Agent IDs must match `^[a-z][a-z0-9_-]{0,29}$`
- Each agent requires its own Telegram bot token

---

## Related

- Full agent creation guide: [docs/CREATE_AGENT.md](../docs/CREATE_AGENT.md)
- Agent versioning: `sdk_bridge/orchestrator.py` — `bump_agent_version()`, `rollback_agent_version()`
- Agent template: `agents/_template/`
