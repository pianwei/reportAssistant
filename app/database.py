from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlparse

import pymysql
from pymysql.cursors import DictCursor

from app.loader import LoadedReport


SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_id VARCHAR(128) PRIMARY KEY,
    report_name VARCHAR(512) NOT NULL,
    report_type VARCHAR(255) NOT NULL,
    summary_json LONGTEXT NOT NULL,
    source_file TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS report_tags (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    report_id VARCHAR(128) NOT NULL,
    dimension VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    value LONGTEXT NOT NULL,
    completeness VARCHAR(64) NOT NULL,
    source_text LONGTEXT NOT NULL,
    note LONGTEXT NOT NULL,
    UNIQUE KEY uq_report_tags_report_name (report_id, name),
    KEY idx_report_tags_name (name),
    CONSTRAINT fk_report_tags_report FOREIGN KEY (report_id)
        REFERENCES reports(report_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL DEFAULT 'legacy',
    title VARCHAR(255) NOT NULL DEFAULT '新会话',
    feature VARCHAR(32) NOT NULL DEFAULT 'recommendation',
    active_intent VARCHAR(32) NOT NULL DEFAULT 'recommendation',
    skipped_tags_json VARCHAR(2048) NOT NULL DEFAULT '[]',
    clarification_count INT NOT NULL DEFAULT 0,
    refinement_count INT NOT NULL DEFAULT 0,
    expected_tag VARCHAR(255) NULL,
    pending_tag_value LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_sessions_user_updated (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content LONGTEXT NOT NULL,
    message_type VARCHAR(32) NOT NULL DEFAULT 'text',
    request_id VARCHAR(64) NULL,
    payload_json LONGTEXT NULL,
    intent VARCHAR(32) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_messages_session (session_id, id),
    CONSTRAINT fk_messages_session FOREIGN KEY (session_id)
        REFERENCES sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS session_tags (
    session_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    value LONGTEXT NOT NULL,
    dimension VARCHAR(255) NOT NULL,
    confidence DOUBLE NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, name),
    CONSTRAINT fk_session_tags_session FOREIGN KEY (session_id)
        REFERENCES sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS model_profiles (
    profile_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    provider VARCHAR(80) NOT NULL,
    base_url TEXT NOT NULL,
    model VARCHAR(255) NOT NULL,
    encrypted_api_key LONGTEXT NULL,
    timeout_seconds DOUBLE NOT NULL DEFAULT 30,
    json_mode TINYINT(1) NOT NULL DEFAULT 1,
    disable_thinking TINYINT(1) NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 0,
    last_test_status VARCHAR(32) NULL,
    last_test_latency_ms DOUBLE NULL,
    last_test_error LONGTEXT NULL,
    last_test_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_model_profiles_active_updated (is_active, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS model_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_type VARCHAR(32) NOT NULL,
    profile_id VARCHAR(64) NULL,
    success TINYINT(1) NOT NULL,
    latency_ms DOUBLE NULL,
    error_type LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS suggestion_batches (
    batch_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    items_json LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


MIGRATION_COLUMNS = {
    "sessions": {
        "user_id": "VARCHAR(64) NOT NULL DEFAULT 'legacy'",
        "title": "VARCHAR(255) NOT NULL DEFAULT '新会话'",
        "feature": "VARCHAR(32) NOT NULL DEFAULT 'recommendation'",
        "active_intent": "VARCHAR(32) NOT NULL DEFAULT 'recommendation'",
        "skipped_tags_json": "VARCHAR(2048) NOT NULL DEFAULT '[]'",
        "refinement_count": "INT NOT NULL DEFAULT 0",
        "expected_tag": "VARCHAR(255) NULL",
        "pending_tag_value": "LONGTEXT NULL",
    },
    "messages": {
        "message_type": "VARCHAR(32) NOT NULL DEFAULT 'text'",
        "request_id": "VARCHAR(64) NULL",
        "payload_json": "LONGTEXT NULL",
        "intent": "VARCHAR(32) NULL",
    },
}


class _CompatRow(dict[str, Any]):
    def __init__(self, values: dict[str, Any]):
        super().__init__({
            key: value.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(value, (datetime, date)) else value
            for key, value in values.items()
        })

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _Result:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int):
        self._rows = [_CompatRow(row) for row in rows]
        self.rowcount = rowcount

    def fetchone(self) -> _CompatRow | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[_CompatRow]:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _MySQLConnection:
    def __init__(self, raw: Any):
        self.raw = raw

    def __enter__(self) -> "_MySQLConnection":
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> None:
        try:
            self.rollback() if exc_type else self.commit()
        finally:
            self.raw.close()

    def execute(self, sql: str, params: Any = None) -> _Result:
        cursor = self.raw.cursor()
        try:
            cursor.execute(sql.replace("?", "%s"), params or ())
            rows = list(cursor.fetchall()) if cursor.description else []
            return _Result(rows, cursor.rowcount)
        finally:
            cursor.close()

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url.strip()

    def connect(self) -> _MySQLConnection:
        if not self.database_url.startswith(("mysql://", "mysql+pymysql://")):
            raise ValueError("DATABASE_URL 必须使用 mysql:// 或 mysql+pymysql:// 协议")
        parsed = urlparse(self.database_url.replace("mysql+pymysql://", "mysql://", 1))
        database_name = unquote(parsed.path.lstrip("/"))
        if not parsed.hostname or not parsed.username or not database_name:
            raise ValueError("DATABASE_URL 必须包含 MySQL 主机、用户名和数据库名")
        query = parse_qs(parsed.query)
        charset = query.get("charset", ["utf8mb4"])[0]
        connect_timeout = int(query.get("connect_timeout", ["10"])[0])
        raw = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=unquote(parsed.username),
            password=unquote(parsed.password or ""),
            database=database_name,
            charset=charset,
            connect_timeout=connect_timeout,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
            cursorclass=DictCursor,
        )
        return _MySQLConnection(raw)

    def _migrate(self, conn: _MySQLConnection) -> None:
        for table, definitions in MIGRATION_COLUMNS.items():
            existing = {
                row["COLUMN_NAME"]
                for row in conn.execute(
                    """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?""",
                    (table,),
                )
            }
            for name, definition in definitions.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def rebuild(self, reports: Iterable[LoadedReport]) -> tuple[int, int]:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
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
                WHERE session_id=? ORDER BY id DESC LIMIT ?) AS recent_messages ORDER BY id""",
                (session_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def get_recent_user_questions(self, session_id: str, limit: int = 5) -> list[dict[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT content FROM (SELECT id, content FROM messages
                WHERE session_id=? AND role='user' AND message_type='text'
                AND (intent IS NULL OR intent<>'greeting')
                ORDER BY id DESC LIMIT ?) AS recent_questions ORDER BY id""",
                (session_id, limit),
            ).fetchall()
        return [{"role": "user", "content": row["content"]} for row in rows]

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

    @staticmethod
    def _conversation_filters(user_id: str | None = None,
                              feature: str | None = None,
                              keyword: str | None = None,
                              days: int | None = None) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id:
            clauses.append("s.user_id=?"); params.append(user_id)
        if feature:
            # A session can contain several routed functions and is then marked
            # as ``mixed``. Filter on user-message intents so operators can
            # still locate one function inside a mixed conversation.
            if feature == "mixed":
                clauses.append("s.feature=?"); params.append(feature)
            else:
                clauses.append(
                    "EXISTS (SELECT 1 FROM messages fm "
                    "WHERE fm.session_id=s.session_id AND fm.role='user' AND fm.intent=?)"
                )
                params.append(feature)
        if keyword:
            clauses.append(
                "EXISTS (SELECT 1 FROM messages km "
                "WHERE km.session_id=s.session_id AND km.content LIKE ?)"
            )
            params.append(f"%{keyword}%")
        if days is not None:
            clauses.append("s.created_at>=DATE_SUB(CURRENT_TIMESTAMP, INTERVAL ? DAY)")
            params.append(days)
        return clauses, params

    def list_conversations(self, user_id: str | None = None, limit: int = 20,
                           cursor: str | None = None, feature: str | None = None,
                           keyword: str | None = None,
                           days: int | None = None) -> dict[str, Any]:
        clauses, params = self._conversation_filters(user_id, feature, keyword, days)
        if cursor:
            clauses.append("s.updated_at<?"); params.append(cursor)
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

    def export_conversation_messages(self, user_id: str | None = None,
                                     feature: str | None = None,
                                     keyword: str | None = None,
                                     days: int | None = None) -> list[dict[str, Any]]:
        clauses, params = self._conversation_filters(user_id, feature, keyword, days)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""SELECT s.session_id,s.title,s.user_id,s.feature,
        s.created_at AS session_created_at,s.updated_at AS session_updated_at,
        m.id AS message_id,m.role,m.intent,m.message_type,m.request_id,
        m.content,m.payload_json,m.created_at AS message_created_at
        FROM sessions s LEFT JOIN messages m ON m.session_id=s.session_id
        {where} ORDER BY s.created_at DESC,m.id ASC"""
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def upsert_session_tags(self, session_id: str, tags: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            for tag in tags:
                sql = """INSERT INTO session_tags(session_id,name,value,dimension,confidence)
                VALUES (?,?,?,?,?) ON DUPLICATE KEY UPDATE
                value=VALUES(value),dimension=VALUES(dimension),confidence=VALUES(confidence),
                updated_at=CURRENT_TIMESTAMP"""
                conn.execute(sql, (session_id, tag["name"], tag["value"], tag["dimension"], tag["confidence"]))

    def get_session_tags(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name,value,dimension,confidence FROM session_tags WHERE session_id=? ORDER BY updated_at,name",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_session_tags(self, session_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM session_tags WHERE session_id=?", (session_id,))
            conn.execute(
                """UPDATE sessions SET expected_tag=NULL,pending_tag_value=NULL,
                clarification_count=0,updated_at=CURRENT_TIMESTAMP WHERE session_id=?""",
                (session_id,),
            )

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
                """SELECT m.content,m.intent FROM messages m
                JOIN sessions s ON s.session_id=m.session_id
                JOIN (SELECT session_id FROM sessions WHERE user_id=?
                      ORDER BY updated_at DESC LIMIT 5) AS recent_sessions
                  ON recent_sessions.session_id=s.session_id
                WHERE s.user_id=? AND m.role='user' ORDER BY m.id DESC LIMIT ?""",
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
            VALUES (?,?,?,?,?,?,?,?,?)""", (
                data["profile_id"], data["name"], data["provider"], data["base_url"],
                data["model"], data["encrypted_api_key"], data["timeout_seconds"],
                data["json_mode"], data["disable_thinking"],
            ))

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
            conn.execute("UPDATE model_profiles SET is_active=0 WHERE is_active=1")
            conn.execute("UPDATE model_profiles SET is_active=1,updated_at=CURRENT_TIMESTAMP WHERE profile_id=?", (profile_id,))
            conn.commit()

    def delete_model_profile(self, profile_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM model_profiles WHERE profile_id=? AND is_active=0", (profile_id,))
        return cursor.rowcount > 0
