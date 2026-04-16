-- ClaudeClaw OS — Hive Mind Schema v2
-- Existing key-value memory (facts / preferences / context)

CREATE TABLE IF NOT EXISTS memory (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL CHECK(category IN ('fact', 'preference', 'context')),
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    pinned      INTEGER DEFAULT 0,
    ttl_expires_at TEXT DEFAULT NULL,
    source_agent TEXT DEFAULT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_key ON memory(category, key);

-- ── MEMORY v2 ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,
    chat_id         TEXT,
    agent_id        TEXT,
    summary         TEXT NOT NULL,
    raw_text        TEXT,
    entities        TEXT DEFAULT '[]',
    topics          TEXT DEFAULT '[]',
    importance      REAL DEFAULT 0.5,
    salience        REAL NOT NULL DEFAULT 1.0,
    pinned          INTEGER DEFAULT 0,
    superseded_by   TEXT REFERENCES memories(id),
    consolidated    INTEGER DEFAULT 0,
    embedding       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_accessed   TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_agent     ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_salience  ON memories(salience DESC);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    summary,
    entities,
    topics,
    content='memories',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, summary, entities, topics)
    VALUES (new.rowid, new.id, new.summary, new.entities, new.topics);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_update
AFTER UPDATE OF summary, entities, topics ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, summary, entities, topics)
    VALUES ('delete', old.rowid, old.id, old.summary, old.entities, old.topics);
    INSERT INTO memories_fts(rowid, id, summary, entities, topics)
    VALUES (new.rowid, new.id, new.summary, new.entities, new.topics);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, summary, entities, topics)
    VALUES ('delete', old.rowid, old.id, old.summary, old.entities, old.topics);
END;

CREATE TABLE IF NOT EXISTS consolidations (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT,
    insights    TEXT,
    patterns    TEXT DEFAULT '[]',
    contradictions TEXT DEFAULT '[]',
    memory_ids  TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consolidations_agent ON consolidations(agent_id);

-- ── MULTI-AGENT HIVE MIND LOG ─────────────────────────────────────────────
-- Shared bulletin board: agents post here after completing work so other
-- agents can stay aware of what the team has done.

CREATE TABLE IF NOT EXISTS hive_mind_log (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    action      TEXT NOT NULL CHECK(action IN ('complete','update','handoff','error','info')),
    summary     TEXT NOT NULL,
    artifacts   TEXT DEFAULT '{}',
    tags        TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hive_log_agent ON hive_mind_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_hive_log_ts    ON hive_mind_log(created_at DESC);

-- ── PROJECTS ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    path        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    status      TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived', 'paused')),
    tags        TEXT DEFAULT '[]'
);

-- ── AUDIT LOG ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT,
    chat_id     TEXT,
    action      TEXT NOT NULL CHECK(action IN
                  ('message','command','delegation','unlock','lock','kill','blocked','denied')),
    detail      TEXT,
    blocked     INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_agent  ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(created_at DESC);

-- ── MISSION CONTROL ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL DEFAULT 'ops',
    chat_id     TEXT,
    prompt      TEXT NOT NULL,
    schedule    TEXT NOT NULL,
    next_run    TEXT NOT NULL,
    status      TEXT DEFAULT 'active' CHECK(status IN ('active','paused','running','error')),
    last_run    TEXT,
    last_result TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sched_status  ON scheduled_tasks(status);
CREATE INDEX IF NOT EXISTS idx_sched_nextrun ON scheduled_tasks(next_run);

CREATE TABLE IF NOT EXISTS mission_tasks (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    prompt         TEXT NOT NULL,
    assigned_agent TEXT,
    status         TEXT DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed','cancelled')),
    priority       INTEGER DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
    result         TEXT,
    created_at     TEXT NOT NULL,
    completed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_mission_status   ON mission_tasks(status);
CREATE INDEX IF NOT EXISTS idx_mission_priority ON mission_tasks(priority, created_at);

-- ── AGENT LOGS ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_logs (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    agent       TEXT NOT NULL,
    task        TEXT,
    result      TEXT,
    error       TEXT,
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_logs_agent     ON agent_logs(agent);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON agent_logs(timestamp DESC);
