# Agent Avatar — Export & Import

Avatars are automatically included in agent export packages and restored when
the package is imported into another ClaudeClaw OS instance.

---

## Supported formats

| Extension | Notes |
|---|---|
| `.png` | Recommended — lossless, transparent backgrounds work |
| `.jpg` / `.jpeg` | Lossy, no transparency |
| `.webp` | Modern format, good compression |

The dashboard displays avatars as circular thumbnails. PNG with a
transparent background gives the cleanest result.

---

## Where avatars are stored

All avatar files live in `dashboard/static/avatars/` and are named after their
agent ID:

```
dashboard/static/avatars/
├── comms.png
├── content.png
├── cicd.png
└── ...
```

The filename stem must match the agent ID exactly. The extension can be any of
the four supported formats.

---

## How export works

When you click **↓ Export** (or call `GET /api/agents/{id}/export`), the server
checks for an avatar file in `dashboard/static/avatars/` in this order:

```
{agent_id}.png  →  {agent_id}.jpg  →  {agent_id}.jpeg  →  {agent_id}.webp
```

The first match is added to the ZIP as `avatar.{ext}` (the agent ID is stripped
from the filename — only the extension is kept):

```
cicd_agent_package/
├── agent.yaml
├── CLAUDE.md
├── cicd_agent.py
├── avatar.png          ← original: dashboard/static/avatars/cicd.png
└── manifest.json
```

If no avatar file exists, the entry is omitted from the package — the import
will simply create an agent with no avatar.

---

## How import works

When a package is imported (via the dashboard **↑ Import Agent** button or
`POST /api/agents/import`), the server:

1. Scans the ZIP for an entry named `avatar.{ext}` at the package root.
2. Validates the extension is one of `png`, `jpg`, `jpeg`, or `webp`.
3. Writes the file to `dashboard/static/avatars/{agent_id}.{ext}`.

The agent ID comes from `agent.yaml` inside the same package — not from the
filename inside the ZIP — so path traversal is impossible.

**Example:** importing `cicd_agent_package.zip` that contains `avatar.png`
writes the file to:

```
dashboard/static/avatars/cicd.png
```

The dashboard immediately shows the avatar on the agent card after a successful
import (no restart required).

---

## Adding an avatar manually

If you created an agent without an avatar, drop an image into the avatars
directory using the correct naming convention:

```bash
# Copy your image (rename it to match the agent ID)
cp my-image.png dashboard/static/avatars/{agent_id}.png
```

Refresh the dashboard — the avatar appears straight away.

**Sizing guidelines:**
- Minimum: 128 × 128 px
- Recommended: 256 × 256 px or 512 × 512 px
- The dashboard renders avatars at 48 × 48 px (circular crop), so fine detail
  is not visible at normal scale but higher resolution looks better on retina
  displays.

---

## Overwriting an existing avatar on import

If the destination instance already has an avatar for the same agent ID, the
import will silently overwrite it (same behaviour as overwriting the agent
config when the overwrite checkbox is checked). The old file is not archived —
make a manual backup first if you need to preserve it.

---

## What happens when there is no avatar

- The dashboard shows a fallback placeholder (the agent's color swatch).
- Export still works — `avatar.*` is simply absent from the ZIP.
- Import still works — the agent is registered without an avatar.

---

## Related

- [AGENT_EXPORT.md](AGENT_EXPORT.md) — Full export/import guide
- [CREATE_AGENT.md](CREATE_AGENT.md) — Creating a new agent (includes avatar section)
- [scripts/README.md](../scripts/README.md) — `create_agent.py` wizard (includes avatar instructions)
- `dashboard/static/avatars/` — Avatar storage directory
