"""Hive Mind — SQLite interface (v2)."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = os.getenv("HIVE_MIND_DB_PATH", "./hive_mind/polar.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Salience decay rates per day
_DECAY_PINNED   = 0.0
_DECAY_HIGH     = 0.01   # importance >= 0.8
_DECAY_MID      = 0.02   # importance >= 0.5
_DECAY_LOW      = 0.05   # importance < 0.5
_SALIENCE_FLOOR = 0.05   # hard-delete below this


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    with _connect() as conn:
        conn.executescript(schema)


class HiveMindDB:

    def __init__(self):
        init_db()

    # ──────────────────────────────────────────────────────────────
    # Legacy key-value memory (facts / preferences / context)
    # ──────────────────────────────────────────────────────────────

    def read_memory(self, category: Optional[str] = None, key: Optional[str] = None) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            if category and key:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE category=? AND key=?"
                    " AND (ttl_expires_at IS NULL OR ttl_expires_at > ?)",
                    (category, key, now),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE category=?"
                    " AND (ttl_expires_at IS NULL OR ttl_expires_at > ?)",
                    (category, now),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory"
                    " WHERE (ttl_expires_at IS NULL OR ttl_expires_at > ?)",
                    (now,),
                ).fetchall()
        return [dict(r) for r in rows]

    def read_pinned(self) -> list[dict]:
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM memory WHERE pinned=1").fetchall()
        return [dict(r) for r in rows]

    def write_memory(
        self,
        category: str,
        key: str,
        value: str,
        pinned: bool = False,
        ttl_hours: Optional[int] = 24,
        source_agent: Optional[str] = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        ttl = None
        if category == "context" and ttl_hours:
            ttl = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        entry_id = str(uuid.uuid4())
        with _connect() as conn:
            existing = conn.execute(
                "SELECT id FROM memory WHERE category=? AND key=?", (category, key)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE memory SET value=?, pinned=?, ttl_expires_at=?,"
                    " source_agent=?, updated_at=? WHERE category=? AND key=?",
                    (value, int(pinned), ttl, source_agent, now, category, key),
                )
                return existing["id"]
            conn.execute(
                "INSERT INTO memory(id,category,key,value,pinned,ttl_expires_at,"
                "source_agent,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (entry_id, category, key, value, int(pinned), ttl, source_agent, now, now),
            )
        return entry_id

    def delete_memory(self, category: str, key: str) -> None:
        with _connect() as conn:
            conn.execute("DELETE FROM memory WHERE category=? AND key=?", (category, key))

    def purge_expired_context(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            cur = conn.execute(
                "DELETE FROM memory WHERE category='context'"
                " AND ttl_expires_at IS NOT NULL AND ttl_expires_at <= ?", (now,)
            )
            return cur.rowcount

    # ──────────────────────────────────────────────────────────────
    # Memory v2 — semantic memories
    # ──────────────────────────────────────────────────────────────

    def insert_memory(
        self,
        summary: str,
        importance: float,
        agent_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        raw_text: Optional[str] = None,
        entities: Optional[list] = None,
        topics: Optional[list] = None,
        embedding: Optional[str] = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        mem_id = str(uuid.uuid4())
        with _connect() as conn:
            conn.execute(
                "INSERT INTO memories(id,chat_id,agent_id,summary,raw_text,entities,"
                "topics,importance,salience,pinned,consolidated,embedding,"
                "created_at,updated_at,last_accessed) "
                "VALUES(?,?,?,?,?,?,?,?,?,0,0,?,?,?,?)",
                (
                    mem_id, chat_id, agent_id, summary, raw_text,
                    json.dumps(entities or []),
                    json.dumps(topics or []),
                    importance,
                    importance,        # initial salience = importance
                    embedding,
                    now, now, now,
                ),
            )
        return mem_id

    def get_memories_by_agent(self, agent_id: Optional[str] = None) -> list[dict]:
        with _connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE agent_id=? AND superseded_by IS NULL"
                    " ORDER BY salience DESC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE superseded_by IS NULL"
                    " ORDER BY salience DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def get_all_embeddings(self, agent_id: Optional[str] = None) -> list[tuple[str, str]]:
        """Return list of (memory_id, embedding_hex) for non-superseded memories with embeddings."""
        with _connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT id, embedding FROM memories"
                    " WHERE agent_id=? AND embedding IS NOT NULL AND superseded_by IS NULL",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, embedding FROM memories"
                    " WHERE embedding IS NOT NULL AND superseded_by IS NULL"
                ).fetchall()
        return [(r["id"], r["embedding"]) for r in rows]

    def get_recent_high_importance(
        self,
        agent_id: Optional[str] = None,
        min_importance: float = 0.7,
        hours: int = 48,
        limit: int = 5,
    ) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with _connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE agent_id=? AND importance>=?"
                    " AND created_at>=? AND superseded_by IS NULL"
                    " ORDER BY importance DESC LIMIT ?",
                    (agent_id, min_importance, cutoff, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE importance>=?"
                    " AND created_at>=? AND superseded_by IS NULL"
                    " ORDER BY importance DESC LIMIT ?",
                    (min_importance, cutoff, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def search_memories_fts(self, query: str, limit: int = 5) -> list[dict]:
        """Full-text search using FTS5 virtual table."""
        with _connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT m.* FROM memories m"
                    " JOIN memories_fts f ON m.id = f.id"
                    " WHERE memories_fts MATCH ?"
                    " AND m.superseded_by IS NULL"
                    " ORDER BY rank LIMIT ?",
                    (query, limit),
                ).fetchall()
            except Exception:
                # Fallback to LIKE search if FTS5 fails
                like = f"%{query}%"
                rows = conn.execute(
                    "SELECT * FROM memories WHERE (summary LIKE ? OR entities LIKE ? OR topics LIKE ?)"
                    " AND superseded_by IS NULL LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def search_conversation_history(
        self,
        keywords: list[str],
        agent_id: Optional[str] = None,
        day_window: int = 7,
        limit: int = 10,
    ) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=day_window)).isoformat()
        like_clauses = " OR ".join(["summary LIKE ?" for _ in keywords])
        params = [f"%{k}%" for k in keywords] + [cutoff]
        query = f"SELECT * FROM memories WHERE ({like_clauses}) AND created_at>=?"
        if agent_id:
            query += " AND agent_id=?"
            params.append(agent_id)
        query += f" AND superseded_by IS NULL ORDER BY created_at DESC LIMIT {limit}"
        with _connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_memory_by_id(self, mem_id: str) -> Optional[dict]:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()
        return dict(row) if row else None

    def update_salience(self, mem_id: str, new_salience: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "UPDATE memories SET salience=?, updated_at=? WHERE id=?",
                (max(0.0, min(5.0, new_salience)), now, mem_id),
            )

    def update_last_accessed(self, mem_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "UPDATE memories SET last_accessed=? WHERE id=?", (now, mem_id)
            )

    def pin_memory(self, mem_id: str) -> None:
        with _connect() as conn:
            conn.execute("UPDATE memories SET pinned=1 WHERE id=?", (mem_id,))

    def unpin_memory(self, mem_id: str) -> None:
        with _connect() as conn:
            conn.execute("UPDATE memories SET pinned=0 WHERE id=?", (mem_id,))

    def set_superseded_by(self, old_id: str, new_id: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE memories SET superseded_by=?,"
                " importance=importance*0.3, salience=salience*0.5 WHERE id=?",
                (new_id, old_id),
            )

    def mark_memories_consolidated(self, ids: list[str]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with _connect() as conn:
            conn.execute(
                f"UPDATE memories SET consolidated=1 WHERE id IN ({placeholders})", ids
            )

    def get_unconsolidated_memories(self, agent_id: Optional[str] = None) -> list[dict]:
        with _connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE consolidated=0 AND agent_id=?"
                    " AND superseded_by IS NULL ORDER BY created_at ASC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE consolidated=0"
                    " AND superseded_by IS NULL ORDER BY created_at ASC"
                ).fetchall()
        return [dict(r) for r in rows]

    def run_salience_decay(self) -> int:
        """
        Apply daily salience decay to all non-pinned memories.
        Hard-deletes memories below the floor. Returns count deleted.
        """
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, importance, salience, pinned FROM memories"
                " WHERE superseded_by IS NULL"
            ).fetchall()

            deleted = 0
            for row in rows:
                if row["pinned"]:
                    continue
                imp = row["importance"]
                sal = row["salience"]
                if imp >= 0.8:
                    rate = _DECAY_HIGH
                elif imp >= 0.5:
                    rate = _DECAY_MID
                else:
                    rate = _DECAY_LOW
                new_sal = sal * (1.0 - rate)
                if new_sal < _SALIENCE_FLOOR:
                    conn.execute("DELETE FROM memories WHERE id=?", (row["id"],))
                    deleted += 1
                else:
                    conn.execute(
                        "UPDATE memories SET salience=? WHERE id=?",
                        (round(new_sal, 6), row["id"]),
                    )
        return deleted

    # ──────────────────────────────────────────────────────────────
    # Consolidations
    # ──────────────────────────────────────────────────────────────

    def insert_consolidation(
        self,
        agent_id: str,
        insights: str,
        patterns: list,
        contradictions: list,
        memory_ids: list,
    ) -> str:
        con_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO consolidations(id,agent_id,insights,patterns,"
                "contradictions,memory_ids,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    con_id, agent_id, insights,
                    json.dumps(patterns),
                    json.dumps(contradictions),
                    json.dumps(memory_ids),
                    now,
                ),
            )
        return con_id

    def get_latest_consolidations(
        self, agent_id: Optional[str] = None, limit: int = 3
    ) -> list[dict]:
        with _connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM consolidations WHERE agent_id=?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM consolidations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────────────────────
    # Projects
    # ──────────────────────────────────────────────────────────────

    def register_project(self, name: str, path: str, tags: list = None) -> str:
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO projects(id,name,path,created_at,status,tags) VALUES(?,?,?,?,?,?)",
                (entry_id, name, path, now, "active", json.dumps(tags or [])),
            )
        return entry_id

    def get_project(self, name: str) -> Optional[dict]:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def list_projects(self, status: Optional[str] = None) -> list[dict]:
        with _connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM projects WHERE status=?", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM projects").fetchall()
        return [dict(r) for r in rows]

    def update_project_status(self, name: str, status: str) -> None:
        with _connect() as conn:
            conn.execute("UPDATE projects SET status=? WHERE name=?", (status, name))

    # ──────────────────────────────────────────────────────────────
    # Agent logs
    # ──────────────────────────────────────────────────────────────

    def log(
        self,
        agent: str,
        task: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO agent_logs(id,timestamp,agent,task,result,error,duration_ms)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc).isoformat(),
                    agent, task, result, error, duration_ms,
                ),
            )

    # ──────────────────────────────────────────────────────────────
    # Audit log
    # ──────────────────────────────────────────────────────────────

    def audit(
        self,
        action: str,
        agent_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        detail: Optional[str] = None,
        blocked: bool = False,
    ) -> None:
        from datetime import datetime, timezone
        with _connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(agent_id,chat_id,action,detail,blocked,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (agent_id, chat_id, action, detail, int(blocked),
                 datetime.now(timezone.utc).isoformat()),
            )

    def get_audit_log(
        self,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        with _connect() as conn:
            if agent_id and action:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE agent_id=? AND action=?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (agent_id, action, limit),
                ).fetchall()
            elif agent_id:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE agent_id=?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────────────────────
    # Multi-Agent — Hive Mind Log
    # ──────────────────────────────────────────────────────────────

    def hive_post(
        self,
        agent_id: str,
        action: str,
        summary: str,
        artifacts: Optional[dict] = None,
        tags: Optional[list] = None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO hive_mind_log(id,agent_id,action,summary,artifacts,tags,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (entry_id, agent_id, action, summary,
                 json.dumps(artifacts or {}), json.dumps(tags or []), now),
            )
        return entry_id

    def hive_get(self, limit: int = 20, agent_id: Optional[str] = None) -> list[dict]:
        with _connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM hive_mind_log WHERE agent_id=?"
                    " ORDER BY created_at DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM hive_mind_log ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────────────────────
    # Mission Control — Scheduled Tasks
    # ──────────────────────────────────────────────────────────────

    def insert_scheduled_task(
        self,
        agent_id: str,
        prompt: str,
        schedule: str,
        next_run: str,
        chat_id: Optional[str] = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks(id,agent_id,chat_id,prompt,schedule,"
                "next_run,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (task_id, agent_id, chat_id, prompt, schedule, next_run, "active", now),
            )
        return task_id

    def get_due_tasks(self) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE status='active' AND next_run<=?"
                " ORDER BY next_run ASC",
                (now,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_task_running(self, task_id: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='running' WHERE id=?", (task_id,)
            )

    def update_task_after_run(self, task_id: str, result: str, next_run: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='active', last_run=?, last_result=?,"
                " next_run=? WHERE id=?",
                (now, result[:2000] if result else None, next_run, task_id),
            )

    def set_task_error(self, task_id: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='error', last_run=?, last_result=?"
                " WHERE id=?",
                (now, error[:2000], task_id),
            )

    def pause_task(self, task_id: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='paused' WHERE id=?", (task_id,)
            )

    def resume_task(self, task_id: str, next_run: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='active', next_run=? WHERE id=?",
                (next_run, task_id),
            )

    def delete_scheduled_task(self, task_id: str) -> None:
        with _connect() as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))

    def list_scheduled_tasks(self) -> list[dict]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks ORDER BY next_run ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def reset_stuck_tasks(self) -> int:
        """Reset tasks stuck in 'running' state (from a previous crash) back to 'active'."""
        with _connect() as conn:
            cur = conn.execute(
                "UPDATE scheduled_tasks SET status='active' WHERE status='running'"
            )
            return cur.rowcount

    # ──────────────────────────────────────────────────────────────
    # Mission Control — Mission Queue
    # ──────────────────────────────────────────────────────────────

    def insert_mission(
        self,
        title: str,
        prompt: str,
        assigned_agent: Optional[str] = None,
        priority: int = 3,
    ) -> str:
        mission_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO mission_tasks(id,title,prompt,assigned_agent,status,"
                "priority,created_at) VALUES(?,?,?,?,?,?,?)",
                (mission_id, title, prompt, assigned_agent, "queued", priority, now),
            )
        return mission_id

    def get_next_queued_mission(self) -> Optional[dict]:
        """Return the highest-priority queued mission (lowest priority number = highest priority)."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM mission_tasks WHERE status='queued'"
                " ORDER BY priority ASC, created_at ASC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def mark_mission_running(self, mission_id: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE mission_tasks SET status='running' WHERE id=?", (mission_id,)
            )

    def complete_mission(self, mission_id: str, result: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "UPDATE mission_tasks SET status='completed', result=?, completed_at=?"
                " WHERE id=?",
                (result[:4000] if result else None, now, mission_id),
            )

    def fail_mission(self, mission_id: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "UPDATE mission_tasks SET status='failed', result=?, completed_at=?"
                " WHERE id=?",
                (error[:4000], now, mission_id),
            )

    def cancel_mission(self, mission_id: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE mission_tasks SET status='cancelled' WHERE id=?", (mission_id,)
            )

    def list_missions(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        with _connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM mission_tasks WHERE status=?"
                    " ORDER BY priority ASC, created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mission_tasks ORDER BY priority ASC, created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def reset_stuck_missions(self) -> int:
        """Reset missions stuck in 'running' state back to 'queued'."""
        with _connect() as conn:
            cur = conn.execute(
                "UPDATE mission_tasks SET status='queued' WHERE status='running'"
            )
            return cur.rowcount

    # ──────────────────────────────────────────────────────────────
    # Agent Versioning
    # ──────────────────────────────────────────────────────────────

    def snapshot_agent_version(
        self,
        agent_id: str,
        version: str,
        model: str,
        personality: str,
        domains: list,
        color: Optional[str] = None,
        changelog: Optional[str] = None,
        bump_type: str = "minor",
        created_by: str = "system",
    ) -> str:
        """Insert a version snapshot and mark it as the active version."""
        ver_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            # Deactivate previous active version for this agent
            conn.execute(
                "UPDATE agent_versions SET is_active=0 WHERE agent_id=?", (agent_id,)
            )
            conn.execute(
                "INSERT INTO agent_versions(id,agent_id,version,model,personality,"
                "domains,color,changelog,bump_type,is_active,created_by,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,1,?,?)",
                (
                    ver_id, agent_id, version, model, personality,
                    json.dumps(domains or []), color, changelog, bump_type,
                    created_by, now,
                ),
            )
        return ver_id

    def get_active_version(self, agent_id: str) -> Optional[dict]:
        """Return the currently active version snapshot for an agent."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_versions WHERE agent_id=? AND is_active=1",
                (agent_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_agent_versions(self, agent_id: str) -> list[dict]:
        """Return all version snapshots for an agent, newest first."""
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_versions WHERE agent_id=?"
                " ORDER BY created_at DESC",
                (agent_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, agent_id: str, version: str) -> Optional[dict]:
        """Return a specific version snapshot by semver string."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_versions WHERE agent_id=? AND version=?",
                (agent_id, version),
            ).fetchone()
        return dict(row) if row else None

    def activate_version(self, agent_id: str, version: str) -> bool:
        """Set a specific version as active; return False if version not found."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT id FROM agent_versions WHERE agent_id=? AND version=?",
                (agent_id, version),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE agent_versions SET is_active=0 WHERE agent_id=?", (agent_id,)
            )
            conn.execute(
                "UPDATE agent_versions SET is_active=1 WHERE agent_id=? AND version=?",
                (agent_id, version),
            )
        return True

    def get_all_active_versions(self) -> list[dict]:
        """Return the active version snapshot for every agent."""
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_versions WHERE is_active=1 ORDER BY agent_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_logs(self, agent: Optional[str] = None, limit: int = 50) -> list[dict]:
        with _connect() as conn:
            if agent:
                rows = conn.execute(
                    "SELECT * FROM agent_logs WHERE agent=?"
                    " ORDER BY timestamp DESC LIMIT ?",
                    (agent, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]
