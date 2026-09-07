# -*- coding: utf-8 -*-
"""DDL-схема SQLite и совместимые миграции.

SQL вынесен из ``services.database`` специально: при изменении структуры
таблиц достаточно открыть этот файл, а код CRUD-операций не приходится
просматривать целиком.

Важно: новые изменения схемы должны быть обратно совместимыми со старой
базой на Railway. Для уже существующей таблицы добавляйте колонку в
``PROPOSED_POST_COMPAT_COLUMNS`` с безопасным ``DEFAULT``.
"""


# Таблицы создаются в таком порядке при каждом старте. SQLite спокойно
# игнорирует уже существующие таблицы благодаря ``IF NOT EXISTS``.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS bot_content (
        content_key TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        text TEXT,
        image_file_id TEXT,
        send_mode TEXT NOT NULL DEFAULT 'auto',
        updated_at TEXT NOT NULL,
        updated_by INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submissions (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        title TEXT,
        submitted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_explorations (
        user_id INTEGER PRIMARY KEY,
        last_explored_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_exploration_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        room_key TEXT NOT NULL,
        room_name TEXT NOT NULL,
        space_result TEXT NOT NULL,
        traces_result TEXT NOT NULL,
        response_result TEXT NOT NULL,
        revisit_note TEXT,
        explored_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_room_history_user_room_time
    ON room_exploration_history (user_id, room_key, explored_at DESC, id DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS proposed_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_chat_id INTEGER NOT NULL,
        source_message_id INTEGER NOT NULL,
        source_thread_id INTEGER,
        source_link TEXT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        publish_author INTEGER NOT NULL DEFAULT 0,
        creative_group TEXT,
        creative_group_format TEXT NOT NULL DEFAULT 'plain',
        text TEXT NOT NULL,
        text_format TEXT NOT NULL DEFAULT 'plain',
        media_type TEXT,
        file_id TEXT,
        file_unique_id TEXT,
        file_name TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        admin_chat_id INTEGER,
        admin_message_id INTEGER,
        review_thread_id INTEGER,
        scheduled_for TEXT,
        publication_chat_id INTEGER,
        publication_message_id INTEGER,
        created_at TEXT NOT NULL,
        approved_at TEXT,
        rejected_at TEXT,
        published_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS maintenance_tasks (
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS house_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        event_at TEXT NOT NULL,
        reminder_at TEXT,
        broadcast_text TEXT NOT NULL,
        link TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        reminder_sent_at TEXT,
        remind_15_min INTEGER NOT NULL DEFAULT 0,
        reminder_15_sent_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS house_event_registrations (
        event_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        full_name TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        registered_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (event_id, user_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS contests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        external_key TEXT UNIQUE,
        title TEXT NOT NULL,
        button_text TEXT NOT NULL,
        description_html TEXT NOT NULL,
        criteria_html TEXT NOT NULL DEFAULT '',
        show_community_rules INTEGER NOT NULL DEFAULT 0,
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        require_repost INTEGER NOT NULL DEFAULT 0,
        ask_ai INTEGER NOT NULL DEFAULT 0,
        submission_mode TEXT NOT NULL DEFAULT 'both',
        allowed_file_categories TEXT NOT NULL DEFAULT '[]',
        max_submissions INTEGER,
        success_message_html TEXT NOT NULL,
        destination_chat_id INTEGER NOT NULL,
        destination_chat_title TEXT,
        destination_thread_id INTEGER,
        status TEXT NOT NULL DEFAULT 'active',
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        finished_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_contests_status_dates
    ON contests (status, starts_at, ends_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS contest_required_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        username TEXT,
        url TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        UNIQUE (contest_id, channel_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contest_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        full_name TEXT NOT NULL,
        author TEXT NOT NULL,
        title TEXT NOT NULL,
        repost_link TEXT,
        ai_link TEXT,
        submission_format TEXT NOT NULL,
        submitted_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_contest_submissions_contest_user
    ON contest_submissions (contest_id, user_id, submitted_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS keeper_easter_egg (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        status TEXT NOT NULL DEFAULT 'dormant',
        armed_by INTEGER,
        armed_at TEXT,
        claimed_by INTEGER,
        claimed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keeper_group_messages (
        chat_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        message_thread_id INTEGER,
        user_id INTEGER NOT NULL,
        username TEXT,
        full_name TEXT NOT NULL,
        text TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        PRIMARY KEY (chat_id, message_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_keeper_group_messages_recent
    ON keeper_group_messages (chat_id, sent_at DESC, message_id DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS keeper_dialogues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        message_thread_id INTEGER,
        trigger_user_id INTEGER NOT NULL,
        room_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        reply_count INTEGER NOT NULL DEFAULT 1,
        last_bot_message_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_keeper_dialogues_active
    ON keeper_dialogues (chat_id, status, started_at DESC, id DESC)
    """,

)


# Эти колонки появились после первых версий бота. ``init_db`` проверяет их
# отдельно, чтобы не ломать существующую SQLite-базу обычным CREATE TABLE.
PROPOSED_POST_COMPAT_COLUMNS: dict[str, str] = {
    "publish_author": "publish_author INTEGER NOT NULL DEFAULT 0",
    "creative_group": "creative_group TEXT",
    "creative_group_format": "creative_group_format TEXT NOT NULL DEFAULT 'plain'",
    "text_format": "text_format TEXT NOT NULL DEFAULT 'plain'",
    "media_type": "media_type TEXT",
    "file_id": "file_id TEXT",
    "file_unique_id": "file_unique_id TEXT",
    "file_name": "file_name TEXT",
}


HOUSE_EVENT_COMPAT_COLUMNS: dict[str, str] = {
    "remind_15_min": "remind_15_min INTEGER NOT NULL DEFAULT 0",
    "reminder_15_sent_at": "reminder_15_sent_at TEXT",
}
