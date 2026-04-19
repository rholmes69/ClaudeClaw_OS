"""Dashboard — POLAR Operations Center v2

Tabbed control panel with:
  - Overview: agent status, stats, live activity
  - Memory: v2 semantic memory timeline with importance/salience
  - Audit: full audit log with action filtering
  - Projects: project registry
  - War Room: voice agent config
  - SSE: real-time push updates to connected clients
"""

import json
import os
import queue
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
import io
import zipfile

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
from flask_socketio import SocketIO, emit

from hive_mind.db import HiveMindDB

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("DASHBOARD_SECRET_KEY", "polar-dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*")
PORT = int(os.getenv("DASHBOARD_PORT", 5000))

# SSE subscriber queues
_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()


def _push_event(event_type: str, data: dict) -> None:
    """Push an SSE event to all connected clients."""
    payload = json.dumps({"type": event_type, **data})
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


# Background heartbeat so SSE connections stay alive
def _heartbeat():
    while True:
        time.sleep(25)
        _push_event("heartbeat", {"ts": datetime.now(timezone.utc).isoformat()})

threading.Thread(target=_heartbeat, daemon=True).start()


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------
# SSE
# ------------------------------------------------------------------

@app.route("/api/events")
def sse_stream():
    client_q: queue.Queue = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_subscribers.append(client_q)

    def generate():
        try:
            while True:
                try:
                    payload = client_q.get(timeout=30)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            with _sse_lock:
                if client_q in _sse_subscribers:
                    _sse_subscribers.remove(client_q)

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------
# Overview
# ------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    hive = HiveMindDB()
    facts    = hive.read_memory(category="fact")
    prefs    = hive.read_memory(category="preference")
    ctx      = hive.read_memory(category="context")
    projects = hive.list_projects()
    logs     = hive.get_logs(limit=20)
    memories = hive.get_memories_by_agent()
    audit    = hive.get_audit_log(limit=5)
    tasks    = hive.list_scheduled_tasks()
    missions = hive.list_missions(status="queued")

    return jsonify({
        "instance": "POLAR",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hive_mind": {
            "facts": len(facts),
            "preferences": len(prefs),
            "context": len(ctx),
            "v2_memories": len(memories),
        },
        "projects": projects,
        "recent_logs": logs,
        "recent_audit": audit,
        "scheduled_tasks": len(tasks),
        "queued_missions": len(missions),
    })


# ------------------------------------------------------------------
# Memory v2
# ------------------------------------------------------------------

@app.route("/api/memories")
def api_memories():
    hive   = HiveMindDB()
    agent  = request.args.get("agent_id")
    limit  = int(request.args.get("limit", 50))
    mems   = hive.get_memories_by_agent(agent_id=agent)[:limit]
    pinned = hive.read_pinned()
    prefs  = hive.read_memory(category="preference")
    facts  = hive.read_memory(category="fact")
    return jsonify({
        "v2": mems,
        "pinned_kv": pinned,
        "preferences": prefs,
        "facts": facts,
    })


@app.route("/api/memories/search")
def api_memories_search():
    q    = request.args.get("q", "")
    hive = HiveMindDB()
    if not q:
        return jsonify([])
    results = hive.search_memories_fts(q, limit=20)
    return jsonify(results)


@app.route("/api/consolidations")
def api_consolidations():
    hive = HiveMindDB()
    return jsonify(hive.get_latest_consolidations(limit=10))


# ------------------------------------------------------------------
# Audit
# ------------------------------------------------------------------

@app.route("/api/audit")
def api_audit():
    hive   = HiveMindDB()
    agent  = request.args.get("agent_id")
    action = request.args.get("action")
    limit  = int(request.args.get("limit", 100))
    return jsonify(hive.get_audit_log(agent_id=agent, action=action, limit=limit))


# ------------------------------------------------------------------
# Projects & Logs
# ------------------------------------------------------------------

@app.route("/api/projects")
def api_projects():
    hive = HiveMindDB()
    return jsonify(hive.list_projects())


@app.route("/api/logs")
def api_logs():
    hive  = HiveMindDB()
    agent = request.args.get("agent")
    limit = int(request.args.get("limit", 50))
    return jsonify(hive.get_logs(agent=agent, limit=limit))


# ------------------------------------------------------------------
# Multi-Agent
# ------------------------------------------------------------------

@app.route("/api/agents")
def api_agents():
    from sdk_bridge.orchestrator import list_agents
    agents = list_agents()
    avatars_dir = os.path.join(os.path.dirname(__file__), "static", "avatars")
    for a in agents:
        agent_id = a.get("id", "")
        for ext in ("png", "jpg", "jpeg", "webp"):
            fname = f"{agent_id}.{ext}"
            if os.path.exists(os.path.join(avatars_dir, fname)):
                a["avatar"] = f"/static/avatars/{fname}"
                break
    return jsonify(agents)


# ------------------------------------------------------------------
# Agent Versioning
# ------------------------------------------------------------------

@app.route("/api/agents/<agent_id>/versions")
def api_agent_versions(agent_id):
    hive = HiveMindDB()
    versions = hive.list_agent_versions(agent_id)
    return jsonify(versions)


@app.route("/api/agents/<agent_id>/versions/active")
def api_agent_active_version(agent_id):
    hive = HiveMindDB()
    ver = hive.get_active_version(agent_id)
    if not ver:
        return jsonify({"error": "no version found"}), 404
    return jsonify(ver)


@app.route("/api/agents/<agent_id>/versions/bump", methods=["POST"])
def api_agent_bump_version(agent_id):
    from sdk_bridge.orchestrator import bump_agent_version
    data      = request.get_json() or {}
    bump_type = data.get("bump_type", "minor")
    changelog = data.get("changelog", "")
    if bump_type not in ("major", "minor", "patch"):
        return jsonify({"error": "bump_type must be major, minor, or patch"}), 400
    try:
        new_ver = bump_agent_version(agent_id, bump_type=bump_type, changelog=changelog)
        _push_event("version_bumped", {"agent_id": agent_id, "version": new_ver})
        return jsonify({"agent_id": agent_id, "version": new_ver})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/agents/<agent_id>/versions/rollback", methods=["POST"])
def api_agent_rollback(agent_id):
    from sdk_bridge.orchestrator import rollback_agent_version
    data    = request.get_json() or {}
    version = data.get("version", "")
    if not version:
        return jsonify({"error": "version required"}), 400
    try:
        restored = rollback_agent_version(agent_id, version)
        _push_event("version_rollback", {"agent_id": agent_id, "version": version})
        return jsonify(restored)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/versions")
def api_all_active_versions():
    hive = HiveMindDB()
    return jsonify(hive.get_all_active_versions())


@app.route("/api/agents/import", methods=["POST"])
def api_agent_import():
    """
    Import an agent package ZIP uploaded from the dashboard.

    Accepts multipart/form-data with a 'package' file field.
    Optional form field 'overwrite=true' allows replacing an existing agent.

    Validates the ZIP, extracts files safely (no path traversal), writes
    agent.yaml / CLAUDE.md / agent module / avatar into the right directories,
    then snapshots the version in the Hive Mind.
    """
    from pathlib import Path
    from sdk_bridge.orchestrator import get_agent_config, load_registry

    if "package" not in request.files:
        return jsonify({"error": "No file uploaded. Send a multipart field named 'package'."}), 400

    f         = request.files["package"]
    overwrite = request.form.get("overwrite", "false").lower() == "true"

    if not f.filename or not f.filename.endswith(".zip"):
        return jsonify({"error": "File must be a .zip package exported from ClaudeClaw OS."}), 400

    agents_dir  = Path(__file__).parent.parent / "agents"
    avatars_dir = Path(__file__).parent / "static" / "avatars"

    try:
        buf = io.BytesIO(f.read())
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()

            # ── Locate the package root prefix ─────────────────────────────
            # All files are under {agent_id}_agent_package/
            prefix = ""
            for name in names:
                if name.endswith("agent.yaml"):
                    prefix = name[: name.rfind("agent.yaml")]
                    break

            if not prefix:
                return jsonify({"error": "Invalid package: agent.yaml not found in ZIP."}), 400

            # ── Security: validate no path traversal ───────────────────────
            for name in names:
                resolved = (Path("/safe") / name).resolve()
                if not str(resolved).startswith(str(Path("/safe").resolve())):
                    return jsonify({"error": "Invalid package: path traversal detected."}), 400

            # ── Read and validate manifest / agent.yaml ────────────────────
            manifest = {}
            manifest_name = f"{prefix}manifest.json"
            if manifest_name in names:
                manifest = json.loads(zf.read(manifest_name).decode("utf-8"))

            yaml_bytes = zf.read(f"{prefix}agent.yaml").decode("utf-8")

            # Parse agent ID from yaml (minimal parse — no pyyaml dependency)
            agent_id = None
            for line in yaml_bytes.splitlines():
                if line.strip().startswith("id:"):
                    agent_id = line.split(":", 1)[1].strip().strip('"\'')
                    break

            if not agent_id:
                return jsonify({"error": "Cannot determine agent ID from agent.yaml."}), 400

            import re as _re
            if not _re.match(r'^[a-z][a-z0-9_-]{0,29}$', agent_id):
                return jsonify({"error": f"Invalid agent ID '{agent_id}' in package."}), 400

            # ── Check for existing agent ───────────────────────────────────
            existing = get_agent_config(agent_id)
            if existing and not overwrite:
                return jsonify({
                    "error":    f"Agent '{agent_id}' already exists.",
                    "conflict": True,
                    "agent_id": agent_id,
                }), 409

            # ── Extract files ──────────────────────────────────────────────
            agent_dir = agents_dir / agent_id
            agent_dir.mkdir(parents=True, exist_ok=True)

            # agent.yaml
            (agent_dir / "agent.yaml").write_text(yaml_bytes, encoding="utf-8")

            # CLAUDE.md
            claude_name = f"{prefix}CLAUDE.md"
            if claude_name in names:
                (agent_dir / "CLAUDE.md").write_bytes(zf.read(claude_name))

            # Python module
            module_name = f"{prefix}{agent_id}_agent.py"
            if module_name in names:
                (agents_dir / f"{agent_id}_agent.py").write_bytes(zf.read(module_name))

            # Avatar — write to static/avatars preserving extension
            for name in names:
                tail = name[len(prefix):]
                if tail.startswith("avatar.") and "." in tail:
                    ext = tail.rsplit(".", 1)[-1].lower()
                    if ext in ("png", "jpg", "jpeg", "webp"):
                        (avatars_dir / f"{agent_id}.{ext}").write_bytes(zf.read(name))
                        break

            # ── Snapshot version in Hive Mind ──────────────────────────────
            hive = HiveMindDB()

            # Parse version and other fields from yaml minimally
            version     = "1.0.0"
            model       = "claude-sonnet-4-6"
            personality = ""
            domains     = []
            color       = None
            in_domains  = False
            for line in yaml_bytes.splitlines():
                stripped = line.strip()
                if stripped.startswith("version:"):
                    version = stripped.split(":", 1)[1].strip().strip('"\'')
                elif stripped.startswith("model:"):
                    model = stripped.split(":", 1)[1].strip().strip('"\'')
                elif stripped.startswith("personality:"):
                    personality = stripped.split(":", 1)[1].strip().strip('"\'')
                elif stripped.startswith("color:"):
                    color = stripped.split(":", 1)[1].strip().strip('"\'')
                elif stripped.startswith("domains:"):
                    in_domains = True
                elif in_domains and stripped.startswith("- "):
                    domains.append(stripped[2:].strip())
                elif in_domains and not stripped.startswith("-") and stripped:
                    in_domains = False

            # Use manifest version history if available
            changelog = "Imported from package."
            if manifest.get("version_history"):
                active_snap = next(
                    (v for v in manifest["version_history"] if v.get("is_active")),
                    manifest["version_history"][0] if manifest["version_history"] else None,
                )
                if active_snap:
                    version     = active_snap.get("version", version)
                    changelog   = active_snap.get("changelog") or changelog
                    model       = active_snap.get("model", model)

            hive.snapshot_agent_version(
                agent_id=agent_id,
                version=version,
                model=model,
                personality=personality,
                domains=domains,
                color=color,
                changelog=changelog,
                bump_type="major",
                created_by="import",
            )

            _push_event("agent_imported", {"agent_id": agent_id, "version": version})

            return jsonify({
                "ok":         True,
                "agent_id":   agent_id,
                "version":    version,
                "name":       manifest.get("name", agent_id),
                "overwritten": bool(existing),
            }), 201

    except zipfile.BadZipFile:
        return jsonify({"error": "File is not a valid ZIP archive."}), 400
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/agents/<agent_id>/export")
def api_agent_export(agent_id):
    """
    Bundle an agent into a downloadable ZIP containing:
      agent.yaml, CLAUDE.md, avatar image (if any),
      agent Python module (if any), and a manifest.json
      with full version history from the Hive Mind.
    """
    from pathlib import Path
    from sdk_bridge.orchestrator import get_agent_config

    cfg = get_agent_config(agent_id)
    if not cfg:
        return jsonify({"error": f"Agent '{agent_id}' not found."}), 404

    hive        = HiveMindDB()
    versions    = hive.list_agent_versions(agent_id)
    active_ver  = hive.get_active_version(agent_id)
    agents_dir  = Path(__file__).parent.parent / "agents"
    agent_dir   = agents_dir / agent_id
    avatars_dir = Path(__file__).parent / "static" / "avatars"

    buf = io.BytesIO()
    pkg = f"{agent_id}_agent_package"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # agent.yaml
        yaml_path = agent_dir / "agent.yaml"
        if yaml_path.exists():
            zf.write(yaml_path, f"{pkg}/agent.yaml")

        # CLAUDE.md
        claude_path = agent_dir / "CLAUDE.md"
        if claude_path.exists():
            zf.write(claude_path, f"{pkg}/CLAUDE.md")

        # Agent Python module
        module_path = agents_dir / f"{agent_id}_agent.py"
        if module_path.exists():
            zf.write(module_path, f"{pkg}/{agent_id}_agent.py")

        # Avatar image — check all supported extensions
        for ext in ("png", "jpg", "jpeg", "webp"):
            avatar_path = avatars_dir / f"{agent_id}.{ext}"
            if avatar_path.exists():
                zf.write(avatar_path, f"{pkg}/avatar.{ext}")
                break

        # manifest.json — metadata + full version history
        manifest = {
            "agent_id":       agent_id,
            "name":           cfg.get("name", agent_id),
            "active_version": active_ver["version"] if active_ver else None,
            "model":          cfg.get("model"),
            "personality":    cfg.get("personality"),
            "domains":        cfg.get("domains", []),
            "color":          cfg.get("color"),
            "exported_at":    datetime.now(timezone.utc).isoformat(),
            "version_history": [
                {
                    "version":    v["version"],
                    "bump_type":  v["bump_type"],
                    "changelog":  v["changelog"],
                    "model":      v["model"],
                    "is_active":  bool(v["is_active"]),
                    "created_at": v["created_at"],
                    "created_by": v["created_by"],
                }
                for v in versions
            ],
        }
        zf.writestr(f"{pkg}/manifest.json", json.dumps(manifest, indent=2))

        # README.md — quick-start instructions inside the package
        readme = f"""# {cfg.get('name', agent_id)} — Agent Package

Exported from ClaudeClaw OS POLAR on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.

## Active version
{active_ver['version'] if active_ver else 'unknown'}

## Contents
| File | Purpose |
|---|---|
| `agent.yaml` | Agent configuration (id, model, personality, domains) |
| `CLAUDE.md` | Agent system prompt |
| `{agent_id}_agent.py` | Agent Python module (if included) |
| `avatar.*` | Avatar image for the dashboard (if included) |
| `manifest.json` | Full version history and export metadata |

## Installing into a ClaudeClaw OS instance
1. Copy `agent.yaml` and `CLAUDE.md` into `agents/{agent_id}/`
2. Copy `{agent_id}_agent.py` into `agents/`
3. Copy `avatar.*` into `dashboard/static/avatars/`
4. Add the agent to `sdk_bridge/router.py` and `sdk_bridge/main_agent.py`
5. Add the bot token env var to `.env`
6. Run `python scripts/create_agent.py` or call `register_agent()` to snapshot v1.0.0

See `docs/CREATE_AGENT.md` for full wiring instructions.
"""
        zf.writestr(f"{pkg}/README.md", readme)

    buf.seek(0)
    filename = f"{agent_id}_agent_package.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/hive")
def api_hive():
    hive  = HiveMindDB()
    limit = int(request.args.get("limit", 30))
    agent = request.args.get("agent_id")
    return jsonify(hive.hive_get(limit=limit, agent_id=agent))


# ------------------------------------------------------------------
# Mission Control
# ------------------------------------------------------------------

@app.route("/api/tasks")
def api_tasks():
    hive = HiveMindDB()
    return jsonify(hive.list_scheduled_tasks())


@app.route("/api/tasks/<task_id>/pause", methods=["POST"])
def api_task_pause(task_id):
    hive = HiveMindDB()
    hive.pause_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>/resume", methods=["POST"])
def api_task_resume(task_id):
    from scheduler.mission_control import _compute_next_run
    hive = HiveMindDB()
    task = hive.list_scheduled_tasks()
    for t in task:
        if t["id"] == task_id:
            next_run = _compute_next_run(t["schedule"])
            hive.resume_task(task_id, next_run)
            break
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def api_task_delete(task_id):
    hive = HiveMindDB()
    hive.delete_scheduled_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks", methods=["POST"])
def api_task_create():
    from scheduler.mission_control import create_scheduled_task
    data = request.get_json() or {}
    prompt   = data.get("prompt", "")
    schedule = data.get("schedule", "0 9 * * *")
    agent_id = data.get("agent_id", "ops")
    chat_id  = data.get("chat_id")
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    result = create_scheduled_task(prompt=prompt, schedule=schedule, agent_id=agent_id, chat_id=chat_id)
    _push_event("task_created", result)
    return jsonify(result), 201


@app.route("/api/missions")
def api_missions():
    hive   = HiveMindDB()
    status = request.args.get("status")
    limit  = int(request.args.get("limit", 50))
    return jsonify(hive.list_missions(status=status, limit=limit))


@app.route("/api/missions", methods=["POST"])
def api_mission_create():
    from scheduler.mission_control import queue_mission
    data     = request.get_json() or {}
    title    = data.get("title", "Untitled Mission")
    prompt   = data.get("prompt", "")
    agent    = data.get("assigned_agent")
    priority = int(data.get("priority", 3))
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    result = queue_mission(title=title, prompt=prompt, assigned_agent=agent, priority=priority)
    _push_event("mission_created", result)
    return jsonify(result), 201


@app.route("/api/missions/<mission_id>/cancel", methods=["POST"])
def api_mission_cancel(mission_id):
    hive = HiveMindDB()
    hive.cancel_mission(mission_id)
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# SocketIO (kept for live log push)
# ------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    emit("connected", {"instance": "POLAR", "status": "online"})
    _push_event("agent_connect", {"ts": datetime.now(timezone.utc).isoformat()})


@socketio.on("refresh")
def on_refresh():
    hive = HiveMindDB()
    logs = hive.get_logs(limit=10)
    emit("log_update", {"logs": logs})
    _push_event("logs", {"logs": logs})


_DELEGATE_TOOL = {
    "name": "delegate_to_agent",
    "description": (
        "Delegate a task to a specialist agent and return their response. "
        "Use this whenever the user asks for content creation, browsing, research, "
        "finance queries, or any task a specialist can handle better than you. "
        "Do NOT use this for simple system status questions you can answer directly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["comms", "content", "ops", "research", "finance"],
                "description": (
                    "comms: scripts, emails, notifications, browsing web for content. "
                    "content: video structure, thumbnails, trends. "
                    "ops: scheduling, project setup, system ops. "
                    "research: deep web research, technical docs. "
                    "finance: invoices, expenses, payroll."
                ),
            },
            "task": {
                "type": "string",
                "description": "The full task description to pass to the specialist.",
            },
        },
        "required": ["agent", "task"],
    },
}


@app.route("/api/voice", methods=["POST"])
def api_voice():
    """
    War Room voice endpoint with conversation history and agent delegation.
    POLAR answers system questions directly; delegates specialist work to agents.
    """
    import anthropic as _anthropic
    from sdk_bridge.orchestrator import list_agents
    from sdk_bridge.router import AgentRouter

    data    = request.get_json() or {}
    text    = (data.get("text") or "").strip()
    history = data.get("history") or []   # list of {role, content} from the client
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        agents = list_agents()
        agent_lines = "\n".join(
            f"  - {a['name']} ({a['id']}): {', '.join(a.get('domains', []) or [])}"
            for a in agents
        )

        hive        = HiveMindDB()
        recent_logs = hive.get_logs(limit=6)
        kv_facts    = hive.read_memory(category="fact")

        log_lines = "\n".join(
            f"  [{l.get('agent_id','?')}] {(l.get('task') or '')[:80]}"
            for l in recent_logs
        ) or "  No recent activity."

        fact_lines = "\n".join(
            f"  {f.get('key')}: {f.get('value')}"
            for f in (kv_facts or [])
        ) or "  No facts stored."

        system = f"""You are POLAR, the ClaudeClaw Council AI, responding via the War Room voice interface.

You have two modes:
1. Answer directly — for system status, agent info, recent activity, stored facts.
2. Delegate — use the delegate_to_agent tool for any task requiring content creation,
   web browsing, research, finance, or specialist work.

Speak conversationally and concisely (spoken aloud). No bullet points. Under 80 words for direct answers.
When delegating, say a brief "routing to X agent" before calling the tool.

LIVE SYSTEM STATE:

Registered agents ({len(agents)}):
{agent_lines}

Recent activity:
{log_lines}

Stored facts:
{fact_lines}"""

        # Build message history (cap at last 10 turns to stay within context)
        messages = []
        for h in history[-10:]:
            role    = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})

        client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        router = AgentRouter()

        # Allow one delegation round
        for _ in range(2):
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=system,
                tools=[_DELEGATE_TOOL],
                messages=messages,
            )

            if resp.stop_reason != "tool_use":
                break

            # Execute delegation
            tool_results = []
            spoken_prefix = ""
            for block in resp.content:
                if block.type == "text" and block.text.strip():
                    spoken_prefix = block.text.strip()
                if block.type == "tool_use" and block.name == "delegate_to_agent":
                    agent_id     = block.input.get("agent", "ops")
                    task_text    = block.input.get("task", text)
                    try:
                        result   = router.route(agent_id, {"instruction": task_text, "hive_context": ""})
                        agent_response = result.get("response", "Task completed.")
                    except Exception as e:
                        agent_response = f"Agent error: {e}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": agent_response,
                    })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user",      "content": tool_results})

        # Extract final text
        final = ""
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                final = block.text.strip()
                break

        return jsonify({"text": final or "Done."})

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def run_dashboard():
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    run_dashboard()
