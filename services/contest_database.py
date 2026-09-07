# -*- coding: utf-8 -*-
"""SQLite-хранилище конструктора конкурсов."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from config import settings


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(settings.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _now_iso() -> str:
    return datetime.now(settings.MOSCOW_TZ).isoformat(timespec="seconds")


def create_contest(data: dict) -> int:
    """Создать опубликованный конкурс и вернуть ID."""
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO contests (
                external_key, title, button_text, description_html, criteria_html,
                show_community_rules, starts_at, ends_at, require_repost, ask_ai,
                submission_mode, allowed_file_categories, max_submissions,
                success_message_html, destination_chat_id, destination_chat_title,
                destination_thread_id, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                data.get("external_key"), data["title"], data["button_text"],
                data["description_html"], data.get("criteria_html", ""),
                int(bool(data.get("show_community_rules"))), data["starts_at"], data["ends_at"],
                int(bool(data.get("require_repost"))), int(bool(data.get("ask_ai"))),
                data["submission_mode"], json.dumps(data.get("allowed_file_categories", []), ensure_ascii=False),
                data.get("max_submissions"), data["success_message_html"],
                int(data["destination_chat_id"]), data.get("destination_chat_title"),
                data.get("destination_thread_id"), int(data["created_by"]), now, now,
            ),
        )
        contest_id = int(cursor.lastrowid)
        _replace_channels(connection, contest_id, data.get("required_channels", []))
        connection.commit()
        return contest_id


def _replace_channels(connection: sqlite3.Connection, contest_id: int, channels: list[dict]) -> None:
    connection.execute("DELETE FROM contest_required_channels WHERE contest_id = ?", (contest_id,))
    for position, channel in enumerate(channels):
        connection.execute(
            """
            INSERT INTO contest_required_channels (
                contest_id, channel_id, title, username, url, position
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                contest_id, int(channel["channel_id"]), channel["title"],
                channel.get("username"), channel["url"], position,
            ),
        )


def get_contest(contest_id: int):
    with _connect() as connection:
        return connection.execute("SELECT * FROM contests WHERE id = ?", (contest_id,)).fetchone()


def get_contest_by_external_key(external_key: str):
    with _connect() as connection:
        return connection.execute(
            "SELECT * FROM contests WHERE external_key = ?", (external_key,)
        ).fetchone()


def contest_external_key_was_deleted(external_key: str) -> bool:
    """Проверить, удалял ли администратор встроенный конкурс вручную."""
    task_name = f"contest_deleted:{external_key}"
    with _connect() as connection:
        return connection.execute(
            "SELECT 1 FROM maintenance_tasks WHERE name = ?",
            (task_name,),
        ).fetchone() is not None


def get_contest_channels(contest_id: int) -> list[sqlite3.Row]:
    with _connect() as connection:
        return list(
            connection.execute(
                "SELECT * FROM contest_required_channels WHERE contest_id = ? ORDER BY position, id",
                (contest_id,),
            ).fetchall()
        )


def get_visible_contests(limit: int = 12) -> list[sqlite3.Row]:
    now = _now_iso()
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT * FROM contests
                WHERE status = 'active' AND ends_at >= ?
                ORDER BY starts_at, id
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        )


def get_admin_active_contests(limit: int = 50) -> list[sqlite3.Row]:
    now = _now_iso()
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT * FROM contests
                WHERE status = 'active' AND ends_at >= ?
                ORDER BY starts_at, id
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        )


def get_archived_contests(limit: int = 50) -> list[sqlite3.Row]:
    now = _now_iso()
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT * FROM contests
                WHERE status != 'active' OR ends_at < ?
                ORDER BY COALESCE(finished_at, ends_at) DESC, id DESC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        )


def finish_contest(contest_id: int) -> bool:
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE contests
            SET status = 'finished', finished_at = ?, updated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (now, now, contest_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def delete_contest(contest_id: int) -> bool:
    """Безвозвратно удалить конкурс и все связанные с ним данные."""
    with _connect() as connection:
        contest = connection.execute(
            "SELECT external_key FROM contests WHERE id = ?",
            (contest_id,),
        ).fetchone()
        if contest is None:
            return False

        connection.execute("DELETE FROM contest_submissions WHERE contest_id = ?", (contest_id,))
        connection.execute("DELETE FROM contest_required_channels WHERE contest_id = ?", (contest_id,))
        connection.execute("DELETE FROM contests WHERE id = ?", (contest_id,))
        if contest["external_key"]:
            connection.execute(
                "INSERT OR REPLACE INTO maintenance_tasks (name, applied_at) VALUES (?, ?)",
                (f"contest_deleted:{contest['external_key']}", _now_iso()),
            )
        connection.commit()
        return True


def count_user_contest_submissions(contest_id: int, user_id: int) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM contest_submissions WHERE contest_id = ? AND user_id = ?",
            (contest_id, user_id),
        ).fetchone()
    return int(row["count"])


def count_contest_submissions(contest_id: int) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM contest_submissions WHERE contest_id = ?",
            (contest_id,),
        ).fetchone()
    return int(row["count"])


def list_contest_submissions(contest_id: int, limit: int = 100) -> list[sqlite3.Row]:
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT * FROM contest_submissions
                WHERE contest_id = ?
                ORDER BY submitted_at, id
                LIMIT ?
                """,
                (contest_id, limit),
            ).fetchall()
        )


def save_contest_submission(
    *, contest_id: int, user_id: int, username: str | None, full_name: str,
    author: str, title: str, repost_link: str | None, ai_link: str | None,
    submission_format: str,
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO contest_submissions (
                contest_id, user_id, username, full_name, author, title,
                repost_link, ai_link, submission_format, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contest_id, user_id, username, full_name, author, title,
                repost_link, ai_link, submission_format, _now_iso(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def delete_contest_submissions_for_user(user_id: int) -> int:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM contest_submissions WHERE user_id = ?", (user_id,))
        connection.commit()
        return cursor.rowcount


def delete_contest_submissions_by_username(username: str) -> int:
    normalized = username.strip().lstrip("@")
    if not normalized:
        return 0
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM contest_submissions WHERE username = ? COLLATE NOCASE", (normalized,)
        )
        connection.commit()
        return cursor.rowcount


def clear_contest_submissions() -> int:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM contest_submissions")
        connection.commit()
        return cursor.rowcount


def migrate_legacy_submissions(contest_id: int) -> int:
    """Привязать старые записи к «ЭХО», не дублируя уже перенесённых авторов."""
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO contest_submissions (
                contest_id, user_id, username, full_name, author, title,
                repost_link, ai_link, submission_format, submitted_at
            )
            SELECT ?, old.user_id, old.username, old.full_name, old.full_name,
                   old.title, NULL, NULL, 'legacy', old.submitted_at
            FROM submissions AS old
            WHERE NOT EXISTS (
                SELECT 1 FROM contest_submissions AS current
                WHERE current.contest_id = ? AND current.user_id = old.user_id
            )
            """,
            (contest_id, contest_id),
        )
        connection.commit()
        return cursor.rowcount
