"""SQLite persistence. The application stores transcript originals intentionally."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = settings.database_file
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with db_session() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('Admin','Editor/Reviewer','Viewer')),
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            csrf_token TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            meeting_date TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            original_text TEXT NOT NULL,
            cleaned_lines_json TEXT NOT NULL,
            analysis_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','processing','processed','approved','failed')),
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            approved_by INTEGER REFERENCES users(id),
            approved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_meetings_status_date ON meetings(status, meeting_date DESC);
        CREATE INDEX IF NOT EXISTS idx_meetings_title ON meetings(title);
        CREATE INDEX IF NOT EXISTS idx_meetings_updated ON meetings(updated_at DESC);
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            actor_id INTEGER NOT NULL REFERENCES users(id),
            action TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_history_meeting ON history(meeting_id, id DESC);
        """)
        row = db.execute("SELECT id FROM users WHERE username = ?", (settings.admin_username,)).fetchone()
        if not row:
            from app.auth import hash_password
            db.execute(
                "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                (settings.admin_username, hash_password(settings.admin_password), "Admin", utc_now()),
            )
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (utc_now(),))
        if settings.retention_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.retention_days)).isoformat(timespec="seconds")
            db.execute("DELETE FROM meetings WHERE updated_at < ?", (cutoff,))


def row_to_meeting(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["cleaned_lines"] = json.loads(data.pop("cleaned_lines_json"))
    data["analysis"] = json.loads(data.pop("analysis_json"))
    return data
