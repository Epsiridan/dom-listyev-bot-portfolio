# -*- coding: utf-8 -*-
"""SQLite-хранилище бота.

Модуль изолирует SQL от Telegram-обработчиков. Все публичные функции здесь
синхронные: операции короткие, а aiogram-обработчики используют их как быстрые
атомарные действия над локальной SQLite-базой.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from config import settings
from services.database_schema import (
    HOUSE_EVENT_COMPAT_COLUMNS,
    PROPOSED_POST_COMPAT_COLUMNS,
    SCHEMA_STATEMENTS,
)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Открыть транзакционное соединение и гарантированно закрыть его."""
    connection = sqlite3.connect(settings.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _now_iso() -> str:
    """Единый формат времени для сортируемых ISO-строк в базе."""
    return datetime.now(settings.MOSCOW_TZ).isoformat(timespec="seconds")


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """Получить набор колонок таблицы для простых миграций."""
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    """Добавить колонку, если база была создана старой версией бота."""
    if column_name not in _table_columns(connection, table_name):
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


# --- Инициализация схемы ---------------------------------------------------

def init_db() -> None:
    """Создать таблицы и применить совместимые миграции.

    Сама DDL-схема находится в ``database_schema.py``. Здесь остаётся только
    порядок запуска: сначала таблицы, затем безопасные ALTER TABLE для старых
    баз. Это снижает риск случайно изменить CRUD-код при работе со схемой.
    """
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        for create_statement in SCHEMA_STATEMENTS:
            connection.execute(create_statement)

        for column_name, column_sql in PROPOSED_POST_COMPAT_COLUMNS.items():
            _ensure_column(
                connection,
                table_name="proposed_posts",
                column_name=column_name,
                column_sql=column_sql,
            )
        for column_name, column_sql in HOUSE_EVENT_COMPAT_COLUMNS.items():
            _ensure_column(
                connection,
                table_name="house_events",
                column_name=column_name,
                column_sql=column_sql,
            )
        connection.commit()


# --- Старые конкурсные заявки ----------------------------------------------
def has_submission(user_id: int) -> bool:
    """Проверить, отправлял ли пользователь конкурсную работу."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM submissions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row is not None


def save_submission(
    *,
    user_id: int,
    username: str | None,
    full_name: str,
    title: str,
) -> None:
    """Сохранить факт отправки конкурсной работы, чтобы не принимать дубли."""
    submitted_at = _now_iso()

    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO submissions (
                user_id,
                username,
                full_name,
                title,
                submitted_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, full_name, title, submitted_at),
        )
        connection.commit()


def delete_submission(user_id: int) -> bool:
    """Удалить все конкурсные заявки по Telegram ID."""
    from services.contest_database import delete_contest_submissions_for_user

    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM submissions WHERE user_id = ?",
            (user_id,),
        )
        connection.commit()
        legacy_deleted = cursor.rowcount
    return bool(legacy_deleted + delete_contest_submissions_for_user(user_id))


def delete_submission_by_username(username: str) -> int:
    """Удалить конкурсные заявки по username без учёта регистра."""
    normalized_username = username.strip().lstrip("@")
    if not normalized_username:
        return 0

    from services.contest_database import delete_contest_submissions_by_username

    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM submissions WHERE username = ? COLLATE NOCASE",
            (normalized_username,),
        )
        connection.commit()
        legacy_deleted = cursor.rowcount
    return legacy_deleted + delete_contest_submissions_by_username(normalized_username)


def clear_submissions() -> int:
    """Очистить старые и новые конкурсные заявки."""
    from services.contest_database import clear_contest_submissions

    with _connect() as connection:
        cursor = connection.execute("DELETE FROM submissions")
        connection.commit()
        legacy_deleted = cursor.rowcount
    return legacy_deleted + clear_contest_submissions()


def count_submissions() -> int:
    """Посчитать сохранённые конкурсные заявки."""
    with _connect() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM submissions").fetchone()
    return int(row["count"])


# --- Предложка и очередь публикаций ----------------------------------------
def create_proposed_post(
    *,
    source_chat_id: int,
    source_message_id: int,
    source_thread_id: int | None,
    source_link: str | None,
    user_id: int | None,
    username: str | None,
    full_name: str | None,
    publish_author: bool = False,
    creative_group: str | None = None,
    creative_group_format: str = "plain",
    text: str,
    text_format: str = "plain",
    media_type: str | None = None,
    file_id: str | None = None,
    file_unique_id: str | None = None,
    file_name: str | None = None,
) -> int:
    """Создать запись предложенного поста и вернуть её ID."""
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO proposed_posts (
                source_chat_id,
                source_message_id,
                source_thread_id,
                source_link,
                user_id,
                username,
                full_name,
                publish_author,
                creative_group,
                creative_group_format,
                text,
                text_format,
                media_type,
                file_id,
                file_unique_id,
                file_name,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                source_chat_id,
                source_message_id,
                source_thread_id,
                source_link,
                user_id,
                username,
                full_name,
                int(publish_author),
                creative_group,
                creative_group_format,
                text,
                text_format,
                media_type,
                file_id,
                file_unique_id,
                file_name,
                now,
                now,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def set_proposed_post_review_message(
    post_id: int,
    *,
    admin_chat_id: int,
    admin_message_id: int,
    review_thread_id: int | None,
) -> None:
    """Запомнить, где в админской группе лежит карточка модерации."""
    with _connect() as connection:
        connection.execute(
            """
            UPDATE proposed_posts
            SET admin_chat_id = ?, admin_message_id = ?, review_thread_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (admin_chat_id, admin_message_id, review_thread_id, _now_iso(), post_id),
        )
        connection.commit()


def get_proposed_post(post_id: int) -> sqlite3.Row | None:
    """Получить предложенный пост по ID."""
    with _connect() as connection:
        return connection.execute(
            "SELECT * FROM proposed_posts WHERE id = ?",
            (post_id,),
        ).fetchone()


def update_proposed_post_text(post_id: int, text: str, text_format: str = "plain") -> None:
    """Обновить текст листа после админской правки."""
    with _connect() as connection:
        connection.execute(
            "UPDATE proposed_posts SET text = ?, text_format = ?, updated_at = ? WHERE id = ?",
            (text, text_format, _now_iso(), post_id),
        )
        connection.commit()


def _first_publication_slot(now: datetime | None = None) -> datetime:
    """Ближайший дневной слот публикации по настройкам PUBLICATION_*."""
    now = now or datetime.now(settings.MOSCOW_TZ)
    slot = now.replace(
        hour=settings.PUBLICATION_HOUR,
        minute=settings.PUBLICATION_MINUTE,
        second=0,
        microsecond=0,
    )
    if now >= slot:
        slot += timedelta(days=1)
    return slot


def _next_publication_slot(connection: sqlite3.Connection) -> datetime:
    """Найти следующий свободный слот после уже одобренных публикаций."""
    slot = _first_publication_slot()
    row = connection.execute(
        """
        SELECT scheduled_for
        FROM proposed_posts
        WHERE status = 'approved' AND scheduled_for IS NOT NULL
        ORDER BY scheduled_for DESC
        LIMIT 1
        """,
    ).fetchone()
    if row and row["scheduled_for"]:
        latest = datetime.fromisoformat(row["scheduled_for"])
        if latest >= slot:
            slot = latest + timedelta(days=1)
    return slot


def approve_proposed_post(post_id: int) -> str | None:
    """Одобрить лист и поставить его в конец очереди публикаций."""
    now = _now_iso()
    with _connect() as connection:
        post = connection.execute(
            "SELECT status FROM proposed_posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if post is None:
            return None
        if post["status"] == "published":
            return None

        scheduled_for = _next_publication_slot(connection).isoformat(timespec="seconds")
        connection.execute(
            """
            UPDATE proposed_posts
            SET status = 'approved', scheduled_for = ?, approved_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (scheduled_for, now, now, post_id),
        )
        connection.commit()
        return scheduled_for


def reject_proposed_post(post_id: int) -> bool:
    """Отклонить лист, если он ещё не опубликован."""
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE proposed_posts
            SET status = 'rejected', rejected_at = ?, updated_at = ?
            WHERE id = ? AND status != 'published'
            """,
            (now, now, post_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def mark_proposed_post_published(
    post_id: int,
    *,
    publication_chat_id: int,
    publication_message_id: int | None,
) -> None:
    """Пометить лист опубликованным и сохранить ссылочные ID сообщения."""
    now = _now_iso()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE proposed_posts
            SET status = 'published',
                publication_chat_id = ?,
                publication_message_id = ?,
                published_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (publication_chat_id, publication_message_id, now, now, post_id),
        )
        connection.commit()


def get_due_proposed_posts(limit: int = 5) -> list[sqlite3.Row]:
    """Вернуть одобренные листы, чей scheduled_for уже наступил."""
    now = _now_iso()
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM proposed_posts
                WHERE status = 'approved'
                  AND scheduled_for IS NOT NULL
                  AND scheduled_for <= ?
                ORDER BY scheduled_for ASC, id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        )


def get_approved_proposed_posts(limit: int = 30) -> list[sqlite3.Row]:
    """Вернуть текущую очередь одобренных листов."""
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM proposed_posts
                WHERE status = 'approved'
                  AND scheduled_for IS NOT NULL
                ORDER BY scheduled_for ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def delete_approved_proposed_post_and_shift_queue(
    post_id: int,
) -> tuple[bool, dict[str, Any] | None, list[dict[str, Any]]]:
    """Удалить лист из очереди и сдвинуть следующие публикации на день раньше."""
    with _connect() as connection:
        post = connection.execute(
            """
            SELECT *
            FROM proposed_posts
            WHERE id = ? AND status = 'approved'
            """,
            (post_id,),
        ).fetchone()
        if post is None:
            return False, None, []

        deleted_post = dict(post)
        scheduled_for = post["scheduled_for"]
        connection.execute(
            "DELETE FROM proposed_posts WHERE id = ? AND status = 'approved'",
            (post_id,),
        )

        shifted_posts: list[dict[str, Any]] = []
        if scheduled_for:
            rows = connection.execute(
                """
                SELECT *
                FROM proposed_posts
                WHERE status = 'approved'
                  AND scheduled_for IS NOT NULL
                  AND scheduled_for > ?
                ORDER BY scheduled_for ASC, id ASC
                """,
                (scheduled_for,),
            ).fetchall()
            now = _now_iso()
            for row in rows:
                old_scheduled_for = row["scheduled_for"]
                shifted = (
                    datetime.fromisoformat(old_scheduled_for) - timedelta(days=1)
                ).isoformat(timespec="seconds")
                connection.execute(
                    """
                    UPDATE proposed_posts
                    SET scheduled_for = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (shifted, now, row["id"]),
                )
                shifted_posts.append(
                    {
                        **dict(row),
                        "old_scheduled_for": old_scheduled_for,
                        "scheduled_for": shifted,
                    }
                )

        connection.commit()
        return True, deleted_post, shifted_posts


def count_pending_proposed_posts() -> int:
    """Посчитать листы, ожидающие модерации."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM proposed_posts WHERE status = 'pending'",
        ).fetchone()
    return int(row["count"])



def cleanup_published_proposed_posts(days: int) -> int:
    """Удалить опубликованные листы старше указанного срока хранения."""
    cutoff = (datetime.now(settings.MOSCOW_TZ) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as connection:
        cursor = connection.execute(
            """
            DELETE FROM proposed_posts
            WHERE status = 'published'
              AND published_at IS NOT NULL
              AND published_at <= ?
            """,
            (cutoff,),
        )
        connection.commit()
        return cursor.rowcount



def get_room_exploration_time(user_id: int) -> str | None:
    """Получить время последнего исследования любой комнаты."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT last_explored_at FROM room_explorations WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return row["last_explored_at"]


def get_last_room_exploration_time(user_id: int, room_key: str) -> str | None:
    """Получить время последнего визита пользователя в конкретную комнату."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT explored_at
            FROM room_exploration_history
            WHERE user_id = ? AND room_key = ?
            ORDER BY explored_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, room_key),
        ).fetchone()
    if row is None:
        return None
    return row["explored_at"]


def save_room_exploration(
    *,
    user_id: int,
    room_key: str,
    room_name: str,
    space_result: str,
    traces_result: str,
    response_result: str,
    revisit_note: str | None,
) -> str:
    """Атомарно сохранить кулдаун и полный результат исследования."""
    now = _now_iso()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO room_explorations (user_id, last_explored_at)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_explored_at = excluded.last_explored_at
            """,
            (user_id, now),
        )
        connection.execute(
            """
            INSERT INTO room_exploration_history (
                user_id,
                room_key,
                room_name,
                space_result,
                traces_result,
                response_result,
                revisit_note,
                explored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                room_key,
                room_name,
                space_result,
                traces_result,
                response_result,
                revisit_note,
                now,
            ),
        )
        connection.commit()
    return now


def get_room_exploration_journal(user_id: int) -> list[sqlite3.Row]:
    """Сгруппировать личную историю по нормализованному ключу комнаты."""
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT
                    history.room_key,
                    COUNT(*) AS exploration_count,
                    MAX(history.explored_at) AS last_explored_at,
                    (
                        SELECT latest.room_name
                        FROM room_exploration_history AS latest
                        WHERE latest.user_id = history.user_id
                          AND latest.room_key = history.room_key
                        ORDER BY latest.explored_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS room_name
                FROM room_exploration_history AS history
                WHERE history.user_id = ?
                GROUP BY history.user_id, history.room_key
                ORDER BY last_explored_at DESC, room_name COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
        )


# --- Мероприятия Дома Листьев ----------------------------------------------
def create_house_event(
    *,
    title: str,
    description: str,
    event_at: str,
    reminder_at: str | None,
    broadcast_text: str,
    link: str | None,
    created_by: int,
    remind_15_min: bool = False,
) -> int:
    """Создать мероприятие и вернуть его ID."""
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO house_events (
                title,
                description,
                event_at,
                reminder_at,
                remind_15_min,
                broadcast_text,
                link,
                status,
                created_by,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                title,
                description,
                event_at,
                reminder_at,
                int(remind_15_min),
                broadcast_text,
                link,
                created_by,
                now,
                now,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def get_house_event(event_id: int) -> sqlite3.Row | None:
    """Вернуть мероприятие по ID."""
    with _connect() as connection:
        return connection.execute(
            "SELECT * FROM house_events WHERE id = ?",
            (event_id,),
        ).fetchone()


def get_active_house_events(limit: int = 30) -> list[sqlite3.Row]:
    """Вернуть мероприятия, на которые можно записаться до 30-й минуты."""
    registration_cutoff = (
        datetime.now(settings.MOSCOW_TZ) - timedelta(minutes=30)
    ).isoformat(timespec="seconds")
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM house_events
                WHERE status = 'active'
                  AND event_at >= ?
                ORDER BY event_at ASC, id ASC
                LIMIT ?
                """,
                (registration_cutoff, limit),
            ).fetchall()
        )


def get_archived_house_events(limit: int = 30) -> list[sqlite3.Row]:
    """Вернуть прошедшие или отменённые мероприятия для админского архива."""
    archive_cutoff = (
        datetime.now(settings.MOSCOW_TZ) - timedelta(minutes=30)
    ).isoformat(timespec="seconds")
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM house_events
                WHERE status != 'active'
                   OR event_at < ?
                ORDER BY event_at DESC, id DESC
                LIMIT ?
                """,
                (archive_cutoff, limit),
            ).fetchall()
        )


def get_public_archived_house_events(limit: int = 30) -> list[sqlite3.Row]:
    """Вернуть проведённые мероприятия для пользовательского архива."""
    archive_cutoff = (
        datetime.now(settings.MOSCOW_TZ) - timedelta(minutes=30)
    ).isoformat(timespec="seconds")
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM house_events
                WHERE status = 'active'
                  AND event_at < ?
                ORDER BY event_at DESC, id DESC
                LIMIT ?
                """,
                (archive_cutoff, limit),
            ).fetchall()
        )


def update_house_event_link(event_id: int, link: str | None) -> bool:
    """Добавить или заменить ссылку мероприятия."""
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE house_events
            SET link = ?, updated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (link, _now_iso(), event_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def update_house_event_broadcast_text(event_id: int, broadcast_text: str) -> bool:
    """Обновить текст рассылки мероприятия."""
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE house_events
            SET broadcast_text = ?, updated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (broadcast_text, _now_iso(), event_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def cancel_house_event(event_id: int) -> bool:
    """Отменить активное мероприятие."""
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE house_events
            SET status = 'cancelled', updated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (_now_iso(), event_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def delete_house_event(event_id: int) -> bool:
    """Безвозвратно удалить мероприятие вместе со всеми регистрациями."""
    with _connect() as connection:
        event = connection.execute(
            "SELECT 1 FROM house_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if event is None:
            return False

        connection.execute(
            "DELETE FROM house_event_registrations WHERE event_id = ?",
            (event_id,),
        )
        connection.execute("DELETE FROM house_events WHERE id = ?", (event_id,))
        connection.commit()
        return True


def register_for_house_event(
    *,
    event_id: int,
    user_id: int,
    username: str | None,
    full_name: str,
) -> bool:
    """Записать пользователя на мероприятие или вернуть его после отмены записи."""
    now = _now_iso()
    with _connect() as connection:
        registration_cutoff = (
            datetime.now(settings.MOSCOW_TZ) - timedelta(minutes=30)
        ).isoformat(timespec="seconds")
        event = connection.execute(
            "SELECT 1 FROM house_events WHERE id = ? AND status = 'active' AND event_at >= ?",
            (event_id, registration_cutoff),
        ).fetchone()
        if event is None:
            return False

        connection.execute(
            """
            INSERT INTO house_event_registrations (
                event_id,
                user_id,
                username,
                full_name,
                status,
                registered_at,
                updated_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(event_id, user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                status = 'active',
                updated_at = excluded.updated_at
            """,
            (event_id, user_id, username, full_name, now, now),
        )
        connection.commit()
        return True


def unregister_from_house_event(event_id: int, user_id: int) -> bool:
    """Отменить запись пользователя на мероприятие."""
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE house_event_registrations
            SET status = 'cancelled', updated_at = ?
            WHERE event_id = ? AND user_id = ? AND status = 'active'
            """,
            (now, event_id, user_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def user_is_registered_for_house_event(event_id: int, user_id: int) -> bool:
    """Проверить активную запись пользователя на мероприятие."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM house_event_registrations
            WHERE event_id = ? AND user_id = ? AND status = 'active'
            """,
            (event_id, user_id),
        ).fetchone()
    return row is not None


def count_house_event_registrations(event_id: int) -> int:
    """Посчитать активных участников мероприятия."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM house_event_registrations
            WHERE event_id = ? AND status = 'active'
            """,
            (event_id,),
        ).fetchone()
    return int(row["count"])


def get_house_event_registrations(event_id: int) -> list[sqlite3.Row]:
    """Вернуть активных участников мероприятия."""
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM house_event_registrations
                WHERE event_id = ? AND status = 'active'
                ORDER BY registered_at ASC, user_id ASC
                """,
                (event_id,),
            ).fetchall()
        )


def get_due_house_events(limit: int = 3) -> list[sqlite3.Row]:
    """Вернуть мероприятия, для которых пора отправить рассылку."""
    now_dt = datetime.now(settings.MOSCOW_TZ)
    now = now_dt.isoformat(timespec="seconds")
    registration_cutoff = (now_dt - timedelta(minutes=30)).isoformat(timespec="seconds")
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM house_events
                WHERE status = 'active'
                  AND reminder_at IS NOT NULL
                  AND reminder_at <= ?
                  AND reminder_sent_at IS NULL
                  AND event_at >= ?
                  AND link IS NOT NULL
                  AND TRIM(link) != ''
                ORDER BY reminder_at ASC, id ASC
                LIMIT ?
                """,
                (now, registration_cutoff, limit),
            ).fetchall()
        )


def get_due_house_event_15_min_reminders(limit: int = 3) -> list[sqlite3.Row]:
    """Вернуть мероприятия, для которых наступило дополнительное напоминание."""
    now = datetime.now(settings.MOSCOW_TZ)
    due_before = (now + timedelta(minutes=15)).isoformat(timespec="seconds")
    registration_cutoff = (now - timedelta(minutes=30)).isoformat(timespec="seconds")
    with _connect() as connection:
        return list(
            connection.execute(
                """
                SELECT *
                FROM house_events
                WHERE status = 'active'
                  AND remind_15_min = 1
                  AND event_at <= ?
                  AND event_at >= ?
                  AND reminder_15_sent_at IS NULL
                  AND link IS NOT NULL
                  AND TRIM(link) != ''
                ORDER BY event_at ASC, id ASC
                LIMIT ?
                """,
                (due_before, registration_cutoff, limit),
            ).fetchall()
        )


def mark_house_event_reminder_sent(event_id: int, *, fifteen_minute: bool = False) -> None:
    """Пометить рассылку мероприятия отправленной."""
    now = _now_iso()
    with _connect() as connection:
        sent_column = "reminder_15_sent_at" if fifteen_minute else "reminder_sent_at"
        connection.execute(
            f"UPDATE house_events SET {sent_column} = ?, updated_at = ? WHERE id = ?",
            (now, now, event_id),
        )
        connection.commit()


# --- Редактируемый контент -------------------------------------------------

def get_content_override(content_key: str) -> sqlite3.Row | None:
    """Вернуть админское переопределение блока или None."""
    with _connect() as connection:
        return connection.execute(
            "SELECT * FROM bot_content WHERE content_key = ?", (content_key,)
        ).fetchone()


def list_content_overrides() -> list[sqlite3.Row]:
    with _connect() as connection:
        return list(connection.execute("SELECT * FROM bot_content ORDER BY content_key").fetchall())


def save_content_override(*, content_key: str, title: str, text: str | None,
                          image_file_id: str | None, send_mode: str, updated_by: int) -> None:
    if send_mode not in {"auto", "text", "caption", "separate"}:
        raise ValueError("Неизвестный режим отправки")
    now = _now_iso()
    with _connect() as connection:
        connection.execute(
            """INSERT INTO bot_content (content_key, title, text, image_file_id, send_mode, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(content_key) DO UPDATE SET
                 title=excluded.title, text=excluded.text, image_file_id=excluded.image_file_id,
                 send_mode=excluded.send_mode, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
            (content_key, title, text, image_file_id, send_mode, now, updated_by),
        )


def delete_content_override(content_key: str) -> bool:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM bot_content WHERE content_key = ?", (content_key,))
        return bool(cursor.rowcount)


# --- Пасхалка: разговор со смотрителем ------------------------------------

KEEPER_GROUP_MESSAGE_LIMIT = 2000
KEEPER_DIALOGUE_TTL = timedelta(hours=3)


def arm_keeper_easter_egg(*, armed_by: int) -> None:
    """Взвести одноразовый ответ смотрителя на следующее исследование."""
    now = _now_iso()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO keeper_easter_egg (id, status, armed_by, armed_at)
            VALUES (1, 'armed', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = 'armed',
                armed_by = excluded.armed_by,
                armed_at = excluded.armed_at,
                claimed_by = NULL,
                claimed_at = NULL
            """,
            (armed_by, now),
        )
        connection.commit()


def claim_keeper_easter_egg(*, claimed_by: int) -> bool:
    """Атомарно забрать взведённую пасхалку; только один запрос победит гонку."""
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE keeper_easter_egg
            SET status = 'claimed', claimed_by = ?, claimed_at = ?
            WHERE id = 1 AND status = 'armed'
            """,
            (claimed_by, _now_iso()),
        )
        connection.commit()
        return cursor.rowcount == 1


def save_keeper_group_message(
    *,
    chat_id: int,
    message_id: int,
    message_thread_id: int | None,
    user_id: int,
    username: str | None,
    full_name: str,
    text: str,
    sent_at: str,
) -> None:
    """Сохранить сообщение локально и ограничить объём сырой памяти."""
    cleaned = " ".join(text.split()).strip()[:2500]
    if not cleaned:
        return
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO keeper_group_messages (
                chat_id, message_id, message_thread_id, user_id,
                username, full_name, text, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                message_thread_id,
                user_id,
                username,
                full_name,
                cleaned,
                sent_at,
            ),
        )
        connection.execute(
            """
            DELETE FROM keeper_group_messages
            WHERE chat_id = ?
              AND message_id NOT IN (
                  SELECT message_id
                  FROM keeper_group_messages
                  WHERE chat_id = ?
                  ORDER BY sent_at DESC, message_id DESC
                  LIMIT ?
              )
            """,
            (chat_id, chat_id, KEEPER_GROUP_MESSAGE_LIMIT),
        )
        connection.commit()


def find_keeper_person(chat_id: int, query: str) -> sqlite3.Row | None:
    """Найти в локальной памяти явно названного участника без передачи данных наружу."""
    lowered_query = query.casefold()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
                user_id,
                username,
                full_name,
                COUNT(*) AS message_count,
                MAX(sent_at) AS last_seen_at
            FROM keeper_group_messages
            WHERE chat_id = ?
            GROUP BY user_id, username, full_name
            ORDER BY last_seen_at DESC
            LIMIT 200
            """,
            (chat_id,),
        ).fetchall()

    for row in rows:
        username = str(row["username"] or "").casefold().lstrip("@")
        name_tokens = {
            token.casefold().strip(".,!?()[]{}«»\"'")
            for token in str(row["full_name"] or "").split()
            if len(token.strip(".,!?()[]{}«»\"'")) >= 3
        }
        if (username and f"@{username}" in lowered_query) or any(
            token in lowered_query for token in name_tokens
        ):
            return row
    return None


def find_keeper_record(query: str) -> sqlite3.Row | None:
    """Найти названное событие/конкурс или последнюю завершившуюся запись Дома."""
    lowered_query = query.casefold()
    now = _now_iso()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT 'event' AS record_kind, title, event_at AS happened_at, status
            FROM house_events

            UNION ALL

            SELECT 'contest' AS record_kind, title, ends_at AS happened_at, status
            FROM contests

            ORDER BY happened_at DESC
            LIMIT 50
            """
        ).fetchall()

    for row in rows:
        title_tokens = {
            token.casefold().strip(".,!?()[]{}«»\"'/-")
            for token in str(row["title"]).split()
            if len(token.strip(".,!?()[]{}«»\"'/-")) >= 3
        }
        if any(token in lowered_query for token in title_tokens):
            return row
    asks_about_past = any(
        word in lowered_query
        for word in ("событ", "раньше", "было", "происход", "помнишь")
    )
    if asks_about_past:
        return next((row for row in rows if str(row["happened_at"]) <= now), None)
    return None


def start_keeper_dialogue(
    *,
    chat_id: int,
    message_thread_id: int | None,
    trigger_user_id: int,
    room_name: str,
    last_bot_message_id: int,
) -> int:
    """Открыть одну активную беседу; первая реплика уже отправлена."""
    now = _now_iso()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE keeper_dialogues
            SET status = 'finished', ended_at = ?
            WHERE chat_id = ? AND status IN ('active', 'closing')
            """,
            (now, chat_id),
        )
        cursor = connection.execute(
            """
            INSERT INTO keeper_dialogues (
                chat_id, message_thread_id, trigger_user_id, room_name,
                status, reply_count, last_bot_message_id, started_at
            ) VALUES (?, ?, ?, ?, 'active', 1, ?, ?)
            """,
            (
                chat_id,
                message_thread_id,
                trigger_user_id,
                room_name,
                last_bot_message_id,
                now,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def get_active_keeper_dialogue(
    *,
    chat_id: int,
    message_thread_id: int | None,
) -> sqlite3.Row | None:
    """Найти активный разговор в том же чате и топике."""
    cutoff = (
        datetime.now(settings.MOSCOW_TZ) - KEEPER_DIALOGUE_TTL
    ).isoformat(timespec="seconds")
    with _connect() as connection:
        return connection.execute(
            """
            SELECT *
            FROM keeper_dialogues
            WHERE chat_id = ?
              AND message_thread_id IS ?
              AND status = 'active'
              AND started_at > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, message_thread_id, cutoff),
        ).fetchone()


def advance_keeper_dialogue(
    *,
    dialogue_id: int,
    last_bot_message_id: int,
    finish: bool = False,
) -> bool:
    """Записать очередной ответ, не позволяя двум сообщениям ответить одновременно."""
    now = _now_iso()
    status = "finished" if finish else "active"
    ended_at = now if finish else None
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE keeper_dialogues
            SET reply_count = reply_count + 1,
                last_bot_message_id = ?,
                status = ?,
                ended_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (last_bot_message_id, status, ended_at, dialogue_id),
        )
        connection.commit()
        return cursor.rowcount == 1


def finish_keeper_dialogue(dialogue_id: int) -> None:
    """Закрыть диалог досрочно без дополнительного ответа."""
    with _connect() as connection:
        connection.execute(
            """
            UPDATE keeper_dialogues
            SET status = 'finished', ended_at = ?
            WHERE id = ? AND status IN ('active', 'closing')
            """,
            (_now_iso(), dialogue_id),
        )
        connection.commit()


def claim_due_keeper_dialogue() -> sqlite3.Row | None:
    """Забрать один разговор, которому исполнилось три часа, для финальной реплики."""
    cutoff = (
        datetime.now(settings.MOSCOW_TZ) - KEEPER_DIALOGUE_TTL
    ).isoformat(timespec="seconds")
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM keeper_dialogues
            WHERE status = 'active'
              AND reply_count < 10
              AND started_at <= ?
            ORDER BY started_at ASC, id ASC
            LIMIT 1
            """,
            (cutoff,),
        ).fetchone()
        if row is None:
            return None
        cursor = connection.execute(
            "UPDATE keeper_dialogues SET status = 'closing' "
            "WHERE id = ? AND status = 'active'",
            (row["id"],),
        )
        connection.commit()
        return row if cursor.rowcount == 1 else None


def complete_due_keeper_dialogue(dialogue_id: int) -> None:
    """Зафиксировать автоматически отправленную финальную реплику."""
    with _connect() as connection:
        connection.execute(
            """
            UPDATE keeper_dialogues
            SET status = 'finished', reply_count = reply_count + 1, ended_at = ?
            WHERE id = ? AND status = 'closing'
            """,
            (_now_iso(), dialogue_id),
        )
        connection.commit()


def release_due_keeper_dialogue(dialogue_id: int) -> None:
    """Вернуть диалог в очередь после временной ошибки отправки."""
    with _connect() as connection:
        connection.execute(
            "UPDATE keeper_dialogues SET status = 'active' "
            "WHERE id = ? AND status = 'closing'",
            (dialogue_id,),
        )
        connection.commit()
