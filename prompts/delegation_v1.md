# Agent Delegation Protocol — v1
# POLAR Instance | Created: 2026-04-15

## Purpose

This document defines how the Main Agent delegates tasks to specialist agents and how specialists report results back through the SDK bridge.

## Delegation Flow

```
User Request
    ↓
Main Agent validates chat ID
    ↓
Main Agent loads Hive Mind context
    ↓
Main Agent classifies request → route_to_agent tool
    ↓
SDK Bridge calls specialist agent.receive(task)
    ↓
Specialist executes task
    ↓
Specialist returns structured result
    ↓
Main Agent writes memory_entries to Hive Mind
    ↓
Main Agent returns response to user
```

## Task Object (Main Agent → Specialist)

```json
{
  "instruction": "Full unambiguous task description",
  "context_summary": "Brief summary of relevant Hive Mind context",
  "hive_context": "Full formatted Hive Mind session context string"
}
```

## Result Object (Specialist → Main Agent)

```json
{
  "response": "User-facing output",
  "summary": "One-line log entry",
  "memory_entries": [
    {
      "category": "fact|preference|context",
      "key": "snake_case_key",
      "value": "string value"
    }
  ],
  "duration_ms": 1234
}
```

## Agent Domain Boundaries

| Agent | Owns | Never Touches |
|---|---|---|
| Comms | Scripts, emails, notifications | Finance, research, project creation |
| Content | Trends, video structure, thumbnails | Finance, emails, deep technical docs |
| Ops | Finance, scheduling, scaffolding | Scripts, content, deep research |
| Research | Web research, technical docs | Finance, emails, content calendars |

## Cross-Domain Escalation

If a specialist receives a request outside its domain:
1. Return an error response with `"response": "This request is outside the [Agent] domain."``
2. Do not attempt partial execution.
3. The Main Agent will re-classify and re-route.

## Prompt Chain Limit

No delegation chain should exceed 3 hops without a Hive Mind checkpoint.
At hop 3, write current state to Hive Mind before continuing.

---
_Version: 1.0 | Changed: Initial release_
