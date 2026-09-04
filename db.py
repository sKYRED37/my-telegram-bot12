import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "submissions.db")


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """
    Создаёт файл БД и таблицу submissions, если их ещё нет.
    Вызывается при каждом запуске бота — безопасно вызывать много раз.
    """
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                username      TEXT,
                full_name     TEXT,
                topic_key     TEXT NOT NULL,
                topic_title   TEXT NOT NULL,
                text          TEXT NOT NULL,
                destination   TEXT,
                created_at    TEXT NOT NULL
            )
            """
        )


def save_submission(
    user_id: int,
    username: str | None,
    full_name: str,
    topic_key: str,
    topic_title: str,
    text: str,
    destination: str,
) -> int:
    """Сохраняет одну заявку в БД, возвращает её id."""
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO submissions
                (user_id, username, full_name, topic_key, topic_title, text, destination, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                full_name,
                topic_key,
                topic_title,
                text,
                destination,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cursor.lastrowid


def get_recent(limit: int = 10) -> list[sqlite3.Row]:
    """Последние N заявок, самые новые первыми."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM submissions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return rows


def get_stats() -> dict:
    """
    Возвращает {"total": int, "by_topic": {topic_title: count}}.
    """
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM submissions").fetchone()["c"]
        rows = conn.execute(
            "SELECT topic_title, COUNT(*) AS c FROM submissions GROUP BY topic_title ORDER BY c DESC"
        ).fetchall()
        by_topic = {row["topic_title"]: row["c"] for row in rows}
        return {"total": total, "by_topic": by_topic}
