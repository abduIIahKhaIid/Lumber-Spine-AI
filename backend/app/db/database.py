"""SQLite storage for the case library and assistant conversations.

One short-lived connection per unit of work keeps this safe across threads and
worker processes. The schema is created idempotently on first use.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, created TEXT, payload TEXT)",
    "CREATE TABLE IF NOT EXISTS reviews (case_id TEXT, revision INTEGER, created TEXT,"
    " reviewer TEXT, payload TEXT, PRIMARY KEY(case_id, revision))",
    "CREATE TABLE IF NOT EXISTS chat_threads (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
    " created TEXT NOT NULL, updated TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'english',"
    " case_context TEXT)",
    "CREATE TABLE IF NOT EXISTS chat_messages (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL"
    " REFERENCES chat_threads(id) ON DELETE CASCADE, seq INTEGER NOT NULL, role TEXT NOT NULL,"
    " content TEXT NOT NULL, image TEXT, provider TEXT, model TEXT,"
    " status TEXT NOT NULL DEFAULT 'complete', steps TEXT, created TEXT NOT NULL,"
    " edited INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS chat_messages_thread ON chat_messages(thread_id, seq)",
    "CREATE INDEX IF NOT EXISTS chat_threads_updated ON chat_threads(updated)",
    "CREATE TABLE IF NOT EXISTS chat_assets (thread_id TEXT NOT NULL REFERENCES chat_threads(id)"
    " ON DELETE CASCADE, key TEXT NOT NULL, caption TEXT NOT NULL, image TEXT NOT NULL,"
    " PRIMARY KEY(thread_id, key))",
)

# Columns added after the first release; applied to existing databases on start.
COLUMNS = {"chat_messages": {"reasoning": "TEXT", "extras": "TEXT"}}


def _migrate(db: sqlite3.Connection) -> None:
    for table, columns in COLUMNS.items():
        present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}  # noqa: S608
        for name, kind in columns.items():
            if name not in present:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


_initialized: set[Path] = set()


def database_path() -> Path:
    return get_settings().database_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    if path not in _initialized:
        db.execute("PRAGMA journal_mode = WAL")
        for statement in SCHEMA:
            db.execute(statement)
        _migrate(db)
        db.commit()
        _initialized.add(path)
    try:
        with db:
            yield db
    finally:
        db.close()
