# ClaudeClaw OS — Architect Agent

## Project Overview

ClaudeClaw OS is a modular, multi-agent AI operating system built on the Anthropic Agent SDK. It operates as a "council" of specialist agents coordinated by a central Main Agent (triage manager), with a shared Hive Mind memory layer and multi-channel communication support.

---

## Architecture

### Core Components

| Layer | Role | Technology |
|---|---|---|
| Main Agent | Triage & delegation manager | Claude (Opus/Sonnet) |
| Hive Mind | Persistent memory controller | SQLite + Gemini Flash |
| SDK Bridge | Agent-to-agent orchestration | Anthropic Agent SDK |
| Comms Agent | Messaging, scripts, notifications | Telegram / Slack / Discord |
| Content Agent | Research, trends, video structure | Claude + web search |
| Ops Agent | Finance tracking, scheduling | Claude + cron |
| Research Agent | Deep search, technical docs | Claude + tools |

### Agent Hierarchy

```
User Input (Telegram / Slack / Discord)
        ↓
   Main Agent (Triage)
   ├── checks Hive Mind for in-progress tasks
   ├── routes to specialist agent
   └── never self-executes unless explicitly told to
        ↓
   Specialist Agent (Comms / Content / Ops / Research)
        ↓
   Hive Mind (memory write-back)
        ↓
   User Response
```

---

## Agent Prompts

### 1. Rebuild Mega Prompt (Initial Setup)

**Role:** Project Architect

Before generating any code, ask the user these 6 questions:

1. Which communication channels should be initialized? (Telegram, Slack, Discord)
2. What is the primary voice and personality for the Main Agent?
3. Which local memory folders should be indexed? (e.g., Obsidian vault paths)
4. Which specialist agents are needed? (Comms, Content, Ops, Research)
5. Which advanced features are required? (War Room voice, Dashboard, Cron Scheduler)
6. What are the security parameters? (Chat ID allow-list, PIN lock)

Once answered, generate a modular Node.js/Python structure handling the SDK bridge and state management.

---

### 2. Hive Mind Memory Prompt

**Role:** Memory Controller (Gemini Flash)

Act as a "memory washing machine" over conversation logs. Extract and categorize:

- **Facts** — Fixed data (addresses, project names, API endpoints)
- **Preferences** — How the user likes things structured or communicated
- **Context** — Temporary data relevant to active tasks only

Store in SQLite. Tag fundamental facts (User Name, Business Email, core config) as **Pinned Memory** to persist across all agent sessions.

---

### 3. Agent Delegation Prompt

**Role:** Main Agent — Triage & Operations Manager

> You are the Main Agent of the ClaudeClaw Council. Your primary goal is to remain a manager. Unless explicitly told otherwise, do not execute tasks yourself. Route the user's request to the correct specialist:
>
> - **Comms:** Scriptwriting, emails, Telegram notifications
> - **Content:** Researching trends, thumbnail concepts, video structure
> - **Ops:** Financial tracking, task scheduling, Hive Mind updates
> - **Research:** Deep web searches and technical documentation analysis
>
> Always check the Hive Mind first to see if a related task is already in progress before delegating.

---

## Agent Best Practices

### Delegation & Role Discipline

- The Main Agent is a **manager, not a doer**. It must not self-execute unless explicitly instructed.
- Each specialist agent operates within its defined competency. Do not cross-delegate (e.g., Comms should not run financial queries).
- Agents must always write results back to the Hive Mind before returning to the user.

### Hive Mind Hygiene

- Every agent session should begin with a Hive Mind read to load relevant Pinned Memories and active Context.
- After task completion, agents must categorize and write back new Facts, Preferences, or updated Context.
- Pinned Memories are never overwritten without explicit user confirmation.
- Context entries expire after a configurable TTL (default: 24 hours) unless promoted to Fact or Preference.

### Tool Use

- Agents must use the minimum tools necessary to complete a task.
- Tool calls should be parallelized where inputs are independent (e.g., simultaneous web searches).
- Never call a tool speculatively — only invoke tools when you have enough context to use the result.
- If a tool call fails, log the failure to the Hive Mind as a transient error and surface it to the user before retrying.

### Communication & Response Style

- Main Agent responses to the user should be brief triage confirmations ("Routing to Content Agent...") unless the user asks for detail.
- Specialist agents return structured outputs: summary, result, and any new memory entries flagged for Hive Mind ingestion.
- Never fabricate information. If uncertain, surface the uncertainty and ask a clarifying question or delegate to Research.

### Security

- All inbound requests must be validated against the Chat ID allow-list before routing.
- PIN lock must be enforced on sensitive Ops operations (financial tracking, config changes).
- Never log credentials, tokens, or PII to the Hive Mind. Use environment variables for secrets.
- API keys and auth tokens are loaded exclusively from environment variables — never hardcoded.

### Modular Code Standards

- Each agent is its own module with a defined interface: `receive(task) → result`.
- The SDK bridge handles all inter-agent communication. Agents do not call each other directly.
- State is never held in memory between sessions — always read from and write to the Hive Mind.
- Cron jobs and scheduled tasks are registered through the Ops Agent only.

### Prompting Discipline

- System prompts are versioned and stored in `/prompts/`. Changes require a comment noting what changed and why.
- Avoid prompt chaining longer than 3 hops without a Hive Mind checkpoint to prevent context drift.
- Use structured output formats (JSON) for all inter-agent data exchange so the SDK bridge can parse reliably.

### Failure & Recovery

- If a specialist agent fails, the Main Agent must catch the error, log it to the Hive Mind, and notify the user with the failure reason before offering a retry.
- Critical failures (auth loss, database unavailable) should trigger a graceful shutdown with a user-facing status message — never silent failures.

---

## Project Scaffolding

### New Project Folder Creation

When a user starts a new project or a new ClaudeClaw OS instance, the Ops Agent is responsible for scaffolding the project directory. The Main Agent detects project-creation intent and routes to Ops.

**Trigger phrases (Main Agent should recognize and route to Ops):**
- "Start a new project"
- "Create a project called..."
- "New ClaudeClaw OS for..."
- "Spin up a new agent workspace"

**Ops Agent scaffolding behavior:**

1. Ask the user for the project name if not provided.
2. Sanitize the name: lowercase, hyphens instead of spaces, no special characters.
3. Create the folder under the configured `PROJECTS_ROOT` path.
4. Copy the standard scaffold template into the new folder.
5. Register the new project in the Hive Mind under `projects` with status `active` and creation timestamp.
6. Confirm creation to the user with the full folder path.

**Standard scaffold template** (copied into every new project folder):

```
{project-name}/
├── CLAUDE.md           # Auto-generated project-level agent instructions
├── .env                # Secrets (never committed — copied from template, values blank)
├── prompts/            # Project-specific agent prompt versions
├── hive_mind/          # Project-scoped SQLite memory (separate from OS-level)
├── outputs/            # Agent-generated files, reports, content drafts
├── assets/             # Source files, media, references
└── logs/               # Agent session logs for this project
```

**Ops Agent scaffold prompt:**

> You are the Ops Agent. The user has requested a new project workspace. Do the following in order:
> 1. Confirm the project name with the user.
> 2. Create the directory at `$PROJECTS_ROOT/{sanitized-project-name}`.
> 3. Initialize the standard subfolder structure inside it.
> 4. Write a minimal `CLAUDE.md` into the root of the new project with the project name and creation date.
> 5. Register the project in the Hive Mind: `{ name, path, created_at, status: "active" }`.
> 6. Return the full path and confirm success to the user.

**Hive Mind project registry schema:**

```json
{
  "id": "uuid",
  "name": "project-name",
  "path": "/absolute/path/to/project",
  "created_at": "ISO8601",
  "status": "active | archived | paused",
  "tags": []
}
```

**Rules:**
- Never overwrite an existing folder. If the folder already exists, notify the user and ask to choose a different name or confirm they want to use the existing folder.
- Project names must be unique within `PROJECTS_ROOT`.
- Archiving a project (status → `archived`) does not delete the folder — it only updates the Hive Mind registry.

---

## Directory Structure (Target)

```
ClaudeClaw_OS/
├── CLAUDE.md                  # This file
├── .env                       # Secrets (never committed)
├── sdk_bridge/                # Anthropic Agent SDK orchestration layer
│   ├── main_agent.py
│   └── router.py
├── agents/
│   ├── comms_agent.py
│   ├── content_agent.py
│   ├── ops_agent.py           # Handles project scaffolding
│   └── research_agent.py
├── hive_mind/
│   ├── db.py                  # SQLite interface
│   ├── memory_controller.py   # Gemini Flash memory washing
│   └── schema.sql             # Includes projects registry table
├── prompts/
│   ├── main_agent_v1.md
│   ├── hive_mind_v1.md
│   └── delegation_v1.md
├── channels/
│   ├── telegram.py
│   ├── slack.py
│   └── discord.py
├── scheduler/
│   └── cron_manager.py
├── scaffold/                  # Project scaffold template (copied on new project creation)
│   ├── CLAUDE.md.template
│   ├── .env.template
│   ├── prompts/
│   ├── hive_mind/
│   ├── outputs/
│   ├── assets/
│   └── logs/
└── projects/                  # All user projects live here (one subfolder per project)
    └── {project-name}/
```

---

## Environment Variables Required

```
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
SLACK_BOT_TOKEN=
DISCORD_BOT_TOKEN=
HIVE_MIND_DB_PATH=
PIN_LOCK_HASH=
PROJECTS_ROOT=              # Absolute path where new project folders are created
```

---

## Development Notes

- Use the Anthropic Agent SDK for all agent orchestration — do not implement custom agent loops.
- Default model: `claude-sonnet-4-6` for Main Agent and specialists; `gemini-flash` for Hive Mind memory controller (cost efficiency).
- Upgrade Main Agent to `claude-opus-4-6` for complex multi-hop reasoning tasks when needed.
- All agent-to-agent messages must be logged with timestamps for audit and debugging.
