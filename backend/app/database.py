from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    system_prompt: Optional[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredMessage:
    id: int
    session_id: str
    role: str
    content: str
    metadata: Optional[dict[str, Any]]
    created_at: str


class Database:
    """Thread-safe SQLite persistence manager for sessions and messages."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._conn: Optional[sqlite3.Connection] = None
        if db_path != ":memory:":
            parent = Path(db_path).parent
            if str(parent):
                os.makedirs(parent, exist_ok=True)
        else:
            # Keep a single persistent connection for in-memory SQLite databases.
            self._conn = self._create_connection()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        if self.db_path != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except sqlite3.OperationalError:
                pass
        return conn

    def _get_connection(self) -> tuple[sqlite3.Connection, bool]:
        if self._conn is not None:
            return self._conn, False
        return self._create_connection(), True

    def init_db(self) -> None:
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            session_id TEXT PRIMARY KEY,
                            system_prompt TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS messages (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT NOT NULL,
                            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                            content TEXT NOT NULL,
                            metadata TEXT,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
                        ON messages (session_id, id)
                        """
                    )
            finally:
                if should_close:
                    conn.close()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def check_connection(self) -> bool:
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                row = conn.execute("SELECT 1").fetchone()
                table = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
                ).fetchone()
                return row is not None and table is not None
            finally:
                if should_close:
                    conn.close()

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                row = conn.execute(
                    """
                    SELECT session_id, system_prompt, created_at, updated_at
                    FROM sessions
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if row is None:
                    return None
                return SessionRecord(
                    session_id=row["session_id"],
                    system_prompt=row["system_prompt"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            finally:
                if should_close:
                    conn.close()

    def get_messages(self, session_id: str) -> list[StoredMessage]:
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT id, session_id, role, content, metadata, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id ASC
                    """,
                    (session_id,),
                ).fetchall()
                result: list[StoredMessage] = []
                for row in rows:
                    raw_meta = row["metadata"]
                    parsed_meta = json.loads(raw_meta) if raw_meta else None
                    result.append(
                        StoredMessage(
                            id=row["id"],
                            session_id=row["session_id"],
                            role=row["role"],
                            content=row["content"],
                            metadata=parsed_meta,
                            created_at=row["created_at"],
                        )
                    )
                return result
            finally:
                if should_close:
                    conn.close()

    def save_turn(
        self,
        session_id: str,
        system_prompt: Optional[str],
        user_content: str,
        assistant_content: str,
        assistant_metadata: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(assistant_metadata)
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO sessions (session_id, system_prompt, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(session_id) DO UPDATE SET
                            system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt),
                            updated_at = excluded.updated_at
                        """,
                        (session_id, system_prompt, now, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO messages (session_id, role, content, metadata, created_at)
                        VALUES (?, 'user', ?, NULL, ?)
                        """,
                        (session_id, user_content, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO messages (session_id, role, content, metadata, created_at)
                        VALUES (?, 'assistant', ?, ?, ?)
                        """,
                        (session_id, assistant_content, metadata_json, now),
                    )
            finally:
                if should_close:
                    conn.close()
