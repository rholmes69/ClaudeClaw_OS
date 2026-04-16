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
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
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
