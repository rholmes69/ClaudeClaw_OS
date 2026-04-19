# Agent Skills Reference — ClaudeClaw OS

A complete list of every tool (skill) available to each specialist agent in this
POLAR instance. Skills are the executable tools Claude can call during an agentic
loop to interact with the real world — file systems, browsers, APIs, and external
services.

---

## Main Agent

The Main Agent has no executable tools of its own. It uses a single internal
routing tool (`route_to_agent`) to classify and delegate tasks to a specialist.
It never executes work itself.

| Skill | Description |
|---|---|
| `route_to_agent` | Classifies the user's request and forwards it to the correct specialist agent |

---

## Comms Agent

**Domain:** Scriptwriting, emails, Telegram notifications, social media copy.

| Skill | Description |
|---|---|
| `browser` | Control a real Chrome browser — navigate URLs, read page text, click elements, fill forms, take screenshots |

**Browser workflow:** `open <url>` → `snapshot -i` → `get text body` → `close`

---

## Content Agent

**Domain:** YouTube video structure, trend research, thumbnail concepts, content calendars, hook writing, programmatic video rendering.

| Skill | Description |
|---|---|
| `remotion_scaffold` | Create a new Remotion React/TypeScript video project and install dependencies |
| `remotion_render` | Render a Remotion composition to an mp4 file |
| `remotion_still` | Capture a single frame from a composition as a PNG/JPEG image |
| `remotion_studio` | Returns instructions to launch the Remotion live-preview browser server |

---

## Finance Agent (Angela)

**Domain:** Invoice tracking, expense logging, payroll queries, financial reports.

No executable tools — operates on structured data provided in the instruction or
retrieved from the Hive Mind. A spreadsheet or accounting API integration would
extend this agent's reach.

---

## Ops Agent

**Domain:** Task scheduling, project scaffolding, Hive Mind updates, status reports.

No tool calls via the Anthropic API — the agent intercepts project-scaffold
requests directly in Python and executes them using the file system.

| Built-in capability | Description |
|---|---|
| `scaffold_project` | Creates a new project workspace: directory structure, `CLAUDE.md`, `.env`, sub-folders (`prompts/`, `hive_mind/`, `outputs/`, `assets/`, `logs/`). Registers the project in the Hive Mind. |

---

## Research Agent

**Domain:** Deep web research, technical documentation, competitive analysis,
fact-finding, BBC news briefings.

| Skill | Description |
|---|---|
| `browser` | Control a real Chrome browser — navigate URLs, read page text, click elements, fill forms, take screenshots |
| `bbc_briefing` | Fetch the latest BBC News headlines using a real browser and save a timestamped briefing `.txt` file to `outputs/` |

**Browser workflow:** `open <url>` → `snapshot -i` → `get text body` → `close`

**BBC briefing** accepts an optional `max_chars` parameter (default: 6000) to
limit how much page content is captured.

---

## CI/CD Agent

**Domain:** Git repository management, GitHub operations, code deployment.

### Git tools

| Skill | Description | Required inputs |
|---|---|---|
| `git_status` | Show working tree status of a local repo | `repo_path` |
| `git_pull` | Pull latest changes from remote | `repo_path` · optional: `remote`, `branch` |
| `git_push` | Push committed changes to remote | `repo_path` · optional: `remote`, `branch`, `set_upstream` |
| `git_clone` | Clone a repository to a local directory | `repo_url` · optional: `dest_path` |
| `git_commit` | Stage all changes (`git add -A`) and commit | `repo_path`, `message` |
| `git_branch` | List all branches or create a new one | `repo_path` · optional: `branch_name` |
| `git_checkout` | Switch to a branch (or create and switch with `-b`) | `repo_path`, `branch_name` · optional: `create_new` |

### GitHub API tools

| Skill | Description | Required inputs |
|---|---|---|
| `github_create_pr` | Open a pull request via the GitHub REST API | `owner`, `repo`, `title`, `head` · optional: `body`, `base`, `draft` |
| `github_list_repos` | List repositories for a GitHub user or organisation | `owner` · optional: `limit` |

**Authentication:** `GITHUB_TOKEN` environment variable (set in `.env`). Required
for `github_create_pr` and `github_list_repos`.

---

## Shared skills (importable modules)

These skills live in `skills/` and can be added to any agent by importing them.

| Module | Tool name | What it provides |
|---|---|---|
| `skills/browser.py` | `browser` | Chrome browser automation via `agent-browser` CLI |
| `skills/bbc_briefing.py` | `bbc_briefing` | BBC News fetch + save to `outputs/` |
| `skills/remotion.py` | `remotion_scaffold`, `remotion_render`, `remotion_still`, `remotion_studio` | Remotion programmatic video rendering |

To add a skill to an agent, import the tool definition and executor:

```python
from skills.browser import BROWSER_TOOLS, execute_browser_tool
from skills.bbc_briefing import BBC_BRIEFING_TOOL, execute_bbc_tool
```

Then pass the tool list to `client.messages.create(tools=...)` and route
`tool_use` blocks to the matching executor in your agentic loop.

---

## Skill count summary

| Agent | Skills |
|---|---|
| Main | 1 (routing only) |
| Comms | 1 |
| Content | 4 (Remotion) |
| Finance | 0 |
| Ops | 1 (built-in scaffold) |
| Research | 2 |
| CI/CD | 9 |
| **Total callable skills** | **18** |

---

## Related

- [CREATE_AGENT.md](CREATE_AGENT.md) — How to create a new agent
- [AGENT_EXPORT.md](AGENT_EXPORT.md) — Export and import agents as ZIP packages
- `skills/` — Shared skill modules available to all agents
- `agents/cicd_agent.py` — CI/CD tool definitions and executors
- `agents/research_agent.py` — Research tool definitions and executors
