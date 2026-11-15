"""Persistence for assistant threads and messages (SQLite)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.db.database import connect


def now() -> str:
    return datetime.now(UTC).isoformat()


def _message(row) -> dict:
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "seq": row["seq"],
        "role": row["role"],
        "content": row["content"],
        "image": row["image"],
        "provider": row["provider"],
        "model": row["model"],
        "status": row["status"],
        "steps": json.loads(row["steps"]) if row["steps"] else [],
        "created": row["created"],
        "edited": bool(row["edited"]),
    }


def _thread(row, preview: str | None = None) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "created": row["created"],
        "updated": row["updated"],
        "language": row["language"],
        "has_case": bool(row["case_context"]),
        **({"preview": preview} if preview is not None else {}),
    }


def list_threads(query: str = "", limit: int = 100) -> list[dict]:
    with connect() as db:
        if query:
            like = f"%{query.lower()}%"
            rows = db.execute(
                "SELECT DISTINCT t.* FROM chat_threads t LEFT JOIN chat_messages m"
                " ON m.thread_id = t.id WHERE lower(t.title) LIKE ? OR lower(m.content) LIKE ?"
                " ORDER BY t.updated DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM chat_threads ORDER BY updated DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_thread(row) for row in rows]


def create_thread(title: str, language: str, case_context: dict | None) -> dict:
    thread_id = uuid.uuid4().hex
    stamp = now()
    with connect() as db:
        db.execute(
            "INSERT INTO chat_threads (id, title, created, updated, language, case_context)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                thread_id,
                title,
                stamp,
                stamp,
                language,
                json.dumps(case_context) if case_context else None,
            ),
        )
    return get_thread(thread_id)


def get_thread(thread_id: str, with_messages: bool = True) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        thread = _thread(row)
        thread["case_context"] = json.loads(row["case_context"]) if row["case_context"] else None
        if with_messages:
            thread["messages"] = [
                _message(m)
                for m in db.execute(
                    "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY seq", (thread_id,)
                )
            ]
        return thread


def update_thread(thread_id: str, title: str | None = None, language: str | None = None):
    with connect() as db:
        if title is not None:
            db.execute(
                "UPDATE chat_threads SET title = ?, updated = ? WHERE id = ?",
                (title, now(), thread_id),
            )
        if language is not None:
            db.execute("UPDATE chat_threads SET language = ? WHERE id = ?", (language, thread_id))
    return get_thread(thread_id, with_messages=False)


def delete_thread(thread_id: str) -> bool:
    with connect() as db:
        db.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
        return db.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,)).rowcount > 0


def add_message(thread_id: str, role: str, content: str, **extra) -> dict:
    message_id = uuid.uuid4().hex
    stamp = now()
    with connect() as db:
        seq = db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM chat_messages WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO chat_messages (id, thread_id, seq, role, content, image, provider, model,"
            " status, steps, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                thread_id,
                seq,
                role,
                content,
                extra.get("image"),
                extra.get("provider"),
                extra.get("model"),
                extra.get("status", "complete"),
                json.dumps(extra.get("steps") or []),
                stamp,
            ),
        )
        db.execute("UPDATE chat_threads SET updated = ? WHERE id = ?", (stamp, thread_id))
        row = db.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    return _message(row)


def get_message(thread_id: str, message_id: str) -> dict | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM chat_messages WHERE id = ? AND thread_id = ?", (message_id, thread_id)
        ).fetchone()
        return _message(row) if row else None


def edit_and_truncate(thread_id: str, message_id: str, content: str) -> dict | None:
    """Replace a user message and delete everything after it (Chainlit-style edit)."""
    with connect() as db:
        row = db.execute(
            "SELECT * FROM chat_messages WHERE id = ? AND thread_id = ? AND role = 'user'",
            (message_id, thread_id),
        ).fetchone()
        if row is None:
            return None
        db.execute(
            "DELETE FROM chat_messages WHERE thread_id = ? AND seq > ?", (thread_id, row["seq"])
        )
        db.execute(
            "UPDATE chat_messages SET content = ?, edited = 1 WHERE id = ?", (content, message_id)
        )
        db.execute("UPDATE chat_threads SET updated = ? WHERE id = ?", (now(), thread_id))
        row = db.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    return _message(row)


def truncate_after_last_user(thread_id: str) -> dict | None:
    """Remove trailing assistant messages; return the last user message (for regenerate)."""
    with connect() as db:
        row = db.execute(
            "SELECT * FROM chat_messages WHERE thread_id = ? AND role = 'user'"
            " ORDER BY seq DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        db.execute(
            "DELETE FROM chat_messages WHERE thread_id = ? AND seq > ?", (thread_id, row["seq"])
        )
    return _message(row)


def history(thread_id: str, limit: int = 16) -> list[dict]:
    """Recent turns for the model: completed user/assistant text only."""
    with connect() as db:
        rows = db.execute(
            "SELECT role, content FROM chat_messages WHERE thread_id = ? AND status != 'error'"
            " ORDER BY seq DESC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"][:6000]} for r in reversed(rows) if r["content"]
    ]
