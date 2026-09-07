"""Small SQLite continuity store for local robot life."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


_PRIVATE_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "reasoning",
    "scratchpad",
    "thought",
    "thinking",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_public(value: Any) -> Any:
    """Remove model-private fields recursively before persistence."""
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_public(item)
            for key, item in value.items()
            if str(key).lower() not in _PRIVATE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_public(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class MemoryStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._initialize()

    def _initialize(self) -> None:
        with self.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_time
                    ON events(occurred_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS world_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    action TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('queued', 'running', 'succeeded', 'rejected', 'failed')),
                    intent_json TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_action_runs_time
                    ON action_runs(requested_at DESC, id DESC);
                """
            )
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(self.SCHEMA_VERSION),),
                )
            elif int(row["value"]) != self.SCHEMA_VERSION:
                raise RuntimeError(f"unsupported database schema {row['value']}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def append_event(
        self, kind: str, source: str, payload: Mapping[str, Any] | None = None
    ) -> int:
        public = sanitize_public(payload or {})
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO events(occurred_at, kind, source, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (_now(), kind, source, json.dumps(public, sort_keys=True)),
            )
            return int(cursor.lastrowid)

    def set_state(self, key: str, value: Any) -> None:
        public = sanitize_public(value)
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO world_state(key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, json.dumps(public, sort_keys=True), _now()),
            )

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value_json FROM world_state ORDER BY key"
            ).fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def queue_action(self, action: str, source: str, intent: Mapping[str, Any]) -> int:
        public = sanitize_public(intent)
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO action_runs(requested_at, action, source, status, intent_json) "
                "VALUES (?, ?, ?, 'queued', ?)",
                (_now(), action, source, json.dumps(public, sort_keys=True)),
            )
            return int(cursor.lastrowid)

    def update_action(self, action_id: int, status: str, summary: str = "") -> None:
        if status not in {"running", "succeeded", "rejected", "failed"}:
            raise ValueError(f"invalid terminal/action status: {status}")
        now = _now()
        with self.transaction() as conn:
            if status == "running":
                conn.execute(
                    "UPDATE action_runs SET status=?, started_at=? WHERE id=?",
                    (status, now, action_id),
                )
            else:
                conn.execute(
                    "UPDATE action_runs SET status=?, finished_at=?, summary=? WHERE id=?",
                    (status, now, summary[:500], action_id),
                )

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM action_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["intent"] = json.loads(item.pop("intent_json"))
            result.append(item)
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
