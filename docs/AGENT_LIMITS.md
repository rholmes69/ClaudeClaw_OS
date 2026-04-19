# Agent Instance Limits — ClaudeClaw OS

## Why is there a 20-agent limit?

The limit is a soft guardrail defined in one place:

```python
# sdk_bridge/orchestrator.py
MAX_AGENTS = 20
```

It was set arbitrarily during initial scaffolding to prevent runaway agent creation.
There is no technical reason it must be 20 — no Anthropic API constraint, no database
schema limitation, and nothing in the Agent SDK enforces it.

---

## Real constraints to be aware of

| Constraint | Reality |
|---|---|
| Routing tool enum | Claude handles large enums fine, but very long descriptions can dilute routing accuracy |
| API costs | More agents = more potential parallel Claude calls |
| Telegram tokens | Each agent needs its own dedicated bot token from BotFather |
| Memory / CPU | Agent classes are lazy-loaded and cached — minimal overhead per agent |

---

## How to raise or remove the limit

**Option A — Raise the limit**

Change one line in [sdk_bridge/orchestrator.py](../sdk_bridge/orchestrator.py):

```python
MAX_AGENTS = 50   # or any number you need
```

**Option B — Remove the limit entirely**

Delete the guard block inside `register_agent()` in the same file:

```python
# Remove these lines:
if len(registry) >= MAX_AGENTS:
    raise ValueError(f"Maximum of {MAX_AGENTS} agents reached.")
```

Both the `register_agent()` function and the `scripts/create_agent.py` wizard read
`MAX_AGENTS` from the same constant, so changing it in one place covers both.

---

## Scaling beyond 20 agents

If you plan to run a large council (20+ agents), the more meaningful limit to
watch is the **routing tool description** in
[sdk_bridge/main_agent.py](../sdk_bridge/main_agent.py).

As agents are added, the `ROUTING_TOOL` enum description grows. Keep each agent's
domain description tight (one line, specific keywords) so the Main Agent's
classifier stays accurate. Vague or overlapping descriptions cause mis-routing —
that is a more practical ceiling than any hardcoded number.

**Example of a well-scoped description:**
```python
"cicd: ANYTHING involving git or GitHub — push, pull, clone, commit, "
"branches, pull requests, merging, repo management, deploying code."
```

**Signs the routing description is getting too long:**
- The Main Agent starts routing tasks to the wrong specialist
- Ambiguous requests land on the wrong agent repeatedly
- You have to add "critical routing rules" to the system prompt to correct behaviour

When that happens, consider grouping related agents under a single router agent
rather than adding all agents directly to the Main Agent's enum.
