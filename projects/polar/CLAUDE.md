# POLAR

ClaudeClaw OS — First project instance.

**Created:** 2026-04-15
**Status:** active

## Purpose

POLAR is the primary ClaudeClaw OS workspace. It runs the full agent council:
Comms, Content, Ops, and Research — coordinated by the Main Agent via Telegram.

## Configuration

- **Channel:** Telegram
- **Voice:** Direct and professional
- **Features:** Dashboard, War Room voice, Cron Scheduler
- **Allowed Chat IDs:** See `.env`

## Agents

- **Comms** — scriptwriting, emails, Telegram notifications
- **Content** — trend research, video structure, thumbnail concepts
- **Ops** — financial tracking, scheduling, project scaffolding
- **Research** — deep search, technical documentation

## Notes

- Main Agent model: `claude-sonnet-4-6`
- Hive Mind controller: Gemini Flash
- Dashboard runs on port 5000 (configurable via `DASHBOARD_PORT`)
- War Room voice engine: pyttsx3 (local) or ElevenLabs (cloud)
