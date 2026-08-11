from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.loader import LoadedReport


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY, report_name TEXT NOT NULL, report_type TEXT NOT NULL,
    summary_json TEXT NOT NULL, source_file TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    dimension TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,
    completeness TEXT NOT NULL, source_text TEXT NOT NULL, note TEXT NOT NULL,
    UNIQUE(report_id, name)
);
CREATE INDEX IF NOT EXISTS idx_report_tags_name ON report_tags(name);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'legacy',
    title TEXT NOT NULL DEFAULT '新会话',
    feature TEXT NOT NULL DEFAULT 'recommendation',
    active_intent TEXT NOT NULL DEFAULT 'recommendation',
    skipped_tags_json TEXT NOT NULL DEFAULT '[]',
    clarification_count INTEGER NOT NULL DEFAULT 0,
    refinement_count INTEGER NOT NULL DEFAULT 0,
    expected_tag TEXT,
    pending_tag_value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    request_id TEXT,
    payload_json TEXT,
    intent TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS session_tags (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    name TEXT NOT NULL, value TEXT NOT NULL, dimension TEXT NOT NULL,
    confidence REAL NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(session_id, name)
);
CREATE TABLE IF NOT EXISTS model_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    encrypted_api_key TEXT,
    timeout_seconds REAL NOT NULL DEFAULT 30,
    json_mode INTEGER NOT NULL DEFAULT 1,
    disable_thinking INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    last_test_status TEXT,
    last_test_latency_ms REAL,
    last_test_error TEXT,
    last_test_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_profile
ON model_profiles(is_active) WHERE is_active = 1;
CREATE TABLE IF NOT EXISTS model_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    profile_id TEXT,
    success INTEGER NOT NULL,
    latency_ms REAL,
    error_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS suggestion_batches (
    batch_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    items_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


MIGRATION_COLUMNS = {
    "sessions": {
        "user_id": "TEXT NOT NULL DEFAULT 'legacy'",
        "title": "TEXT NOT NULL DEFAULT '新会话'",
        "feature": "TEXT NOT NULL DEFAULT 'recommendation'",
        "active_intent": "TEXT NOT NULL DEFAULT 'recommendation'",
        "skipped_tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "refinement_count": "INTEGER NOT NULL DEFAULT 0",
        "expected_tag": "TEXT",
        "pending_tag_value": "TEXT",
    },
    "messages": {
        "message_type": "TEXT NOT NULL DEFAULT 'text'",
        "request_id": "TEXT",
        "payload_json": "TEXT",
        "intent": "TEXT",
    },
}


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for table, definitions in MIGRATION_COLUMNS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in definitions.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def rebuild(self, reports: Iterable[LoadedReport]) -> tuple[int, int]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user_updated "
                "ON sessions(user_id, updated_at DESC)"
            )
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM report_tags")
                conn.execute("DELETE FROM reports")
                report_count = tag_count = 0
                for item in reports:
                    summary = item.report.summary.model_dump(by_alias=True)
                    conn.execute(
                        "INSERT INTO reports VALUES (?, ?, ?, ?, ?)",
                        (item.report_id, item.report.summary.report_name,
                         item.report.summary.report_type,
                         json.dumps(summary, ensure_ascii=False), item.source_file),
                    )
                    report_count += 1
                    for tag in item.report.tag_collection.tags:
                        conn.execute(
                            """INSERT INTO report_tags
                            (report_id, dimension, name, value, completeness, source_text, note)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (item.report_id, tag.dimension, tag.name, tag.value,
                             tag.completeness, tag.source_text, tag.note),
                        )
                        tag_count += 1
                conn.commit()
                return report_count, tag_count
            except Exception:
                conn.rollback()
                raise

    # Sessions and messages
    def create_session(self, session_id: str, user_id: str = "legacy", feature: str = "unknown") -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO sessions(session_id, user_id, feature, active_intent)
                VALUES (?, ?, ?, ?)""",
                (session_id, user_id, feature, feature),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def session_exists(self, session_id: str) -> bool:
        return self.get_session(session_id) is not None

    def add_message(self, session_id: str, role: str, content: str,
                    message_type: str = "text", request_id: str | None = None,
                    payload: Any | None = None, intent: str | None = None) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO messages
                (session_id, role, content, message_type, request_id, payload_json, intent)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, role, content, message_type, request_id, payload_json, intent),
            )
            if role == "user":
                conn.execute(
                    """UPDATE sessions SET updated_at=CURRENT_TIMESTAMP,
                    title=CASE WHEN title='新会话' THEN ? ELSE title END WHERE session_id=?""",
                    (content[:30], session_id),
                )
            else:
                conn.execute("UPDATE sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=?", (session_id,))

    def get_messages(self, session_id: str, limit: int = 10) -> list[dict[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT role, content FROM (SELECT id, role, content FROM messages
                WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id""",
                (session_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def get_conversation(self, session_id: str) -> dict[str, Any] | None:
        session = self.get_session(session_id)
        if not session:
            return None
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json")) if item.get("payload_json") else None
            messages.append(item)
        session["messages"] = messages
        session["tags"] = self.get_session_tags(session_id)
        return session

    def list_conversations(self, user_id: str | None = None, limit: int = 20,
                           cursor: str | None = None, feature: str | None = None,
                           keyword: str | None = None) -> dict[str, Any]:
        clauses, params = [], []
        if user_id:
            clauses.append("s.user_id=?"); params.append(user_id)
        if cursor:
            clauses.append("s.updated_at<?"); params.append(cursor)
        if feature:
            # A session can contain several routed functions and is then marked
            # as ``mixed``.  Filter on the intent recorded for each user message
            # so operators can still find (for example) statistics requests in
            # a mixed conversation.
            if feature == "mixed":
                clauses.append("s.feature=?"); params.append(feature)
            else:
                clauses.append(
                    "EXISTS (SELECT 1 FROM messages fm "
                    "WHERE fm.session_id=s.session_id AND fm.role='user' AND fm.intent=?)"
                )
                params.append(feature)
        if keyword:
            clauses.append("EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.session_id AND m.content LIKE ?)")
            params.append(f"%{keyword}%")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""SELECT s.*, COUNT(m.id) message_count FROM sessions s
        LEFT JOIN messages m ON m.session_id=s.session_id {where}
        GROUP BY s.session_id ORDER BY s.updated_at DESC LIMIT ?"""
        params.append(min(max(limit, 1), 100) + 1)
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params)]
        has_more = len(rows) > limit
        items = rows[:limit]
        return {"items": items, "next_cursor": items[-1]["updated_at"] if has_more and items else None}

    def upsert_session_tags(self, session_id: str, tags: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            for tag in tags:
                conn.execute(
                    """INSERT INTO session_tags(session_id,name,value,dimension,confidence)
                    VALUES (?,?,?,?,?) ON CONFLICT(session_id,name) DO UPDATE SET
                    value=excluded.value,dimension=excluded.dimension,confidence=excluded.confidence,
                    updated_at=CURRENT_TIMESTAMP""",
                    (session_id, tag["name"], tag["value"], tag["dimension"], tag["confidence"]),
                )

    def get_session_tags(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name,value,dimension,confidence FROM session_tags WHERE session_id=? ORDER BY updated_at,name",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clarification_count(self, session_id: str) -> int:
        session = self.get_session(session_id)
        return int(session["clarification_count"]) if session else 0

    def set_clarification(self, session_id: str, expected_tag: str,
                          pending_tag_value: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute("""UPDATE sessions SET clarification_count=clarification_count+1,
            expected_tag=?,pending_tag_value=?,updated_at=CURRENT_TIMESTAMP WHERE session_id=?""",
            (expected_tag, pending_tag_value, session_id))

    def expected_tag(self, session_id: str) -> str | None:
        session = self.get_session(session_id)
        return session.get("expected_tag") if session else None

    def pending_tag_value(self, session_id: str) -> str | None:
        session = self.get_session(session_id)
        return session.get("pending_tag_value") if session else None

    def clear_expected_tag(self, session_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET expected_tag=NULL,pending_tag_value=NULL WHERE session_id=?",
                (session_id,),
            )

    def set_session_intent(self, session_id: str, intent: str) -> None:
        session = self.get_session(session_id)
        if not session:
            return
        old_active = session.get("active_intent")
        summary = session.get("feature") or "unknown"
        if summary == "unknown":
            summary = intent
        elif summary not in {intent, "mixed"}:
            summary = "mixed"
        switched = old_active not in {None, "unknown", intent}
        with self.connect() as conn:
            conn.execute(
                """UPDATE sessions SET active_intent=?,feature=?,
                clarification_count=CASE WHEN ? THEN 0 ELSE clarification_count END,
                refinement_count=CASE WHEN ? THEN 0 ELSE refinement_count END,
                expected_tag=CASE WHEN ? THEN NULL ELSE expected_tag END,
                pending_tag_value=CASE WHEN ? THEN NULL ELSE pending_tag_value END,
                skipped_tags_json=CASE WHEN ? THEN '[]' ELSE skipped_tags_json END,
                updated_at=CURRENT_TIMESTAMP WHERE session_id=?""",
                (intent, summary, int(switched), int(switched), int(switched), int(switched), int(switched), session_id),
            )

    def refinement_count(self, session_id: str) -> int:
        session = self.get_session(session_id)
        return int(session.get("refinement_count") or 0) if session else 0

    def increment_refinement(self, session_id: str) -> int:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET refinement_count=refinement_count+1,updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
                (session_id,),
            )
            row = conn.execute(
                "SELECT refinement_count FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        return int(row["refinement_count"]) if row else 0

    def set_expected_tag(self, session_id: str, tag_name: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET expected_tag=?,pending_tag_value=NULL WHERE session_id=?",
                (tag_name, session_id),
            )

    def remove_session_tag(self, session_id: str, tag_name: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM session_tags WHERE session_id=? AND name=?", (session_id, tag_name)
            )
        return cursor.rowcount > 0

    def skipped_tags(self, session_id: str) -> set[str]:
        session = self.get_session(session_id)
        if not session:
            return set()
        try:
            return set(json.loads(session.get("skipped_tags_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            return set()

    def skip_tag(self, session_id: str, tag_name: str) -> None:
        values = sorted(self.skipped_tags(session_id) | {tag_name})
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET skipped_tags_json=?,expected_tag=NULL,pending_tag_value=NULL WHERE session_id=?",
                (json.dumps(values, ensure_ascii=False), session_id),
            )

    def recent_user_messages(self, user_id: str, limit: int = 20) -> list[dict[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT m.content,m.intent FROM messages m JOIN sessions s ON s.session_id=m.session_id
                WHERE s.user_id=? AND m.role='user' AND s.session_id IN (
                    SELECT session_id FROM sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 5
                ) ORDER BY m.id DESC LIMIT ?""",
                (user_id, user_id, limit),
            ).fetchall()
        return [{"content": row["content"], "intent": row["intent"] or ""} for row in reversed(rows)]

    def user_intent_usage(self, user_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT m.intent,COUNT(*) count FROM messages m
                JOIN sessions s ON s.session_id=m.session_id
                WHERE s.user_id=? AND m.role='user' AND m.intent IS NOT NULL
                GROUP BY m.intent""",
                (user_id,),
            ).fetchall()
        return {row["intent"]: int(row["count"]) for row in rows}

    def save_suggestion_batch(self, batch_id: str, user_id: str, items: list[dict[str, str]]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO suggestion_batches(batch_id,user_id,items_json) VALUES (?,?,?)",
                (batch_id, user_id, json.dumps(items, ensure_ascii=False)),
            )

    def get_suggestion_batch(self, batch_id: str | None, user_id: str) -> list[dict[str, str]]:
        if not batch_id:
            return []
        with self.connect() as conn:
            row = conn.execute(
                "SELECT items_json FROM suggestion_batches WHERE batch_id=? AND user_id=?",
                (batch_id, user_id),
            ).fetchone()
        return json.loads(row[0]) if row else []

    # Reports
    def all_reports_with_tags(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            reports = [dict(row) for row in conn.execute("SELECT * FROM reports")]
            tags = [dict(row) for row in conn.execute("SELECT * FROM report_tags")]
        by_report: dict[str, list[dict[str, Any]]] = {}
        for tag in tags:
            by_report.setdefault(tag.pop("report_id"), []).append(tag)
        for report in reports:
            report["summary"] = json.loads(report.pop("summary_json")); report["tags"] = by_report.get(report["report_id"], [])
        return reports

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
            if not row: return None
            tags = conn.execute("SELECT dimension,name,value,completeness,source_text,note FROM report_tags WHERE report_id=? ORDER BY id", (report_id,)).fetchall()
        report = dict(row); report["summary"] = json.loads(report.pop("summary_json")); report["tags"] = [dict(t) for t in tags]
        return report

    def counts(self) -> tuple[int, int]:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]), int(conn.execute("SELECT COUNT(*) FROM report_tags").fetchone()[0])

    def metrics(self) -> dict[str, Any]:
        with self.connect() as conn:
            feature_usage = {
                row["intent"]: int(row["count"])
                for row in conn.execute(
                    """SELECT intent, COUNT(*) AS count FROM messages
                    WHERE role='user' AND intent IS NOT NULL GROUP BY intent"""
                )
            }
            return {
                "users": int(conn.execute("SELECT COUNT(DISTINCT user_id) FROM sessions").fetchone()[0]),
                "sessions": int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
                "messages": int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
                "model_failures": int(conn.execute("SELECT COUNT(*) FROM model_events WHERE success=0").fetchone()[0]),
                "feature_usage": feature_usage,
            }

    # Model profiles
    def list_model_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM model_profiles ORDER BY is_active DESC, updated_at DESC")]

    def get_model_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM model_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        return dict(row) if row else None

    def active_model_profile(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM model_profiles WHERE is_active=1").fetchone()
        return dict(row) if row else None

    def save_model_profile(self, data: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute("""INSERT INTO model_profiles
            (profile_id,name,provider,base_url,model,encrypted_api_key,timeout_seconds,json_mode,disable_thinking)
            VALUES (:profile_id,:name,:provider,:base_url,:model,:encrypted_api_key,:timeout_seconds,:json_mode,:disable_thinking)""", data)

    def update_model_profile(self, profile_id: str, changes: dict[str, Any]) -> None:
        if not changes: return
        assignments = ",".join(f"{key}=?" for key in changes) + ",updated_at=CURRENT_TIMESTAMP"
        with self.connect() as conn:
            conn.execute(f"UPDATE model_profiles SET {assignments} WHERE profile_id=?", [*changes.values(), profile_id])

    def record_model_test(self, profile_id: str, success: bool, latency_ms: float, error: str | None) -> None:
        with self.connect() as conn:
            conn.execute("""UPDATE model_profiles SET last_test_status=?,last_test_latency_ms=?,
            last_test_error=?,last_test_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE profile_id=?""",
            ("success" if success else "failed", latency_ms, error, profile_id))
            conn.execute("INSERT INTO model_events(event_type,profile_id,success,latency_ms,error_type) VALUES ('test',?,?,?,?)",
                         (profile_id, int(success), latency_ms, error))

    def activate_model_profile(self, profile_id: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE model_profiles SET is_active=0 WHERE is_active=1")
            conn.execute("UPDATE model_profiles SET is_active=1,updated_at=CURRENT_TIMESTAMP WHERE profile_id=?", (profile_id,))
            conn.commit()

    def delete_model_profile(self, profile_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM model_profiles WHERE profile_id=? AND is_active=0", (profile_id,))
        return cursor.rowcount > 0
