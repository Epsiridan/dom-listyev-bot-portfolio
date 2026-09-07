# -*- coding: utf-8 -*-
"""Доменная логика конструктора конкурсов."""

import json
import re
from datetime import datetime
from html import escape as html_escape, unescape as html_unescape
from pathlib import PurePath
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from config import settings
from services.contest_database import (
    contest_external_key_was_deleted,
    create_contest,
    get_contest_by_external_key,
    get_contest_channels,
    migrate_legacy_submissions,
)
from services.telegram_utils import thread_kwargs
from services.content import get_text

ECHO_EXTERNAL_KEY = "echo_mercanie_2026"
SUBMISSION_MODES = {"text", "files", "both"}
FILE_CATEGORY_LABELS: dict[str, str] = {
    "txt": "TXT",
    "docx": "DOCX",
    "pdf": "PDF",
    "open_docs": "RTF / ODT",
    "images": "Изображения (JPG, PNG, WEBP)",
    "audio": "Аудио (MP3, WAV, M4A)",
    "video": "Видео (MP4, MOV)",
    "zip": "ZIP-архивы",
}
FILE_CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "txt": {".txt"},
    "docx": {".docx"},
    "pdf": {".pdf"},
    "open_docs": {".rtf", ".odt"},
    "images": {".jpg", ".jpeg", ".png", ".webp"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg"},
    "video": {".mp4", ".mov", ".m4v"},
    "zip": {".zip"},
}
HTML_TAG_RE = re.compile(r"<[^>]+>")


def ensure_echo_contest() -> int | None:
    """Один раз перенести текущий «ЭХО» и его старые заявки в новую модель."""
    contest = get_contest_by_external_key(ECHO_EXTERNAL_KEY)
    if contest is None:
        if contest_external_key_was_deleted(ECHO_EXTERNAL_KEY):
            return None
        contest_id = create_contest(
            {
                "external_key": ECHO_EXTERNAL_KEY,
                "title": "ЭХО // мерцание",
                "button_text": "🎨 Отправить работу на конкурс «ЭХО // мерцание»",
                "description_html": get_text("contest_default_description"),
                "criteria_html": "",
                "show_community_rules": False,
                "starts_at": datetime(2026, 7, 1, 18, 0, tzinfo=settings.MOSCOW_TZ).isoformat(timespec="seconds"),
                "ends_at": datetime(2026, 7, 31, 21, 0, tzinfo=settings.MOSCOW_TZ).isoformat(timespec="seconds"),
                "require_repost": True,
                "ask_ai": True,
                "submission_mode": "both",
                "allowed_file_categories": ["txt", "docx"],
                "max_submissions": 1,
                "success_message_html": get_text("contest_submission_received"),
                "destination_chat_id": settings.ADMIN_GROUP_ID,
                "destination_chat_title": "Админский чат заявок",
                "destination_thread_id": settings.ADMIN_CONTESTS_THREAD_ID,
                "created_by": 0,
                "required_channels": [
                    {
                        "channel_id": settings.PUBLIC_CHANNEL_ID,
                        "title": "Дом Листьев",
                        "username": "house_of_the_leaves",
                        "url": "https://t.me/house_of_the_leaves",
                    },
                    {
                        "channel_id": settings.PARTNER_CHANNEL_ID,
                        "title": "Гильдия искусства",
                        "username": "guild_of_art",
                        "url": "https://t.me/guild_of_art",
                    },
                ],
            }
        )
    else:
        contest_id = int(contest["id"])
    migrate_legacy_submissions(contest_id)
    return contest_id


def parse_contest_datetime(value: str) -> datetime:
    parsed = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")
    return parsed.replace(tzinfo=settings.MOSCOW_TZ)


def format_contest_datetime(value: str | None) -> str:
    if not value:
        return "не указано"
    try:
        parsed = datetime.fromisoformat(value).astimezone(settings.MOSCOW_TZ)
    except ValueError:
        return value
    return parsed.strftime("%d.%m.%Y %H:%M МСК")


def contest_timing_status(contest) -> str:
    if contest is None or contest["status"] != "active":
        return "closed"
    now = datetime.now(settings.MOSCOW_TZ)
    starts_at = datetime.fromisoformat(contest["starts_at"]).astimezone(settings.MOSCOW_TZ)
    ends_at = datetime.fromisoformat(contest["ends_at"]).astimezone(settings.MOSCOW_TZ)
    if now < starts_at:
        return "upcoming"
    if now > ends_at:
        return "closed"
    return "open"


def contest_unavailable_text(contest) -> str:
    if contest is None:
        return "Конкурс не найден."
    if contest_timing_status(contest) == "upcoming":
        return (get_text("contest_too_early")
            .replace("{title}", str(contest["title"]))
            .replace("{starts_at}", format_contest_datetime(contest["starts_at"])))
    return (get_text("contest_closed")
        .replace("{title}", str(contest["title"]))
        .replace("{ends_at}", format_contest_datetime(contest["ends_at"])))


def build_contest_info_html(contest) -> str:
    period = (
        f"🗓 <b>Приём работ:</b> "
        f"{format_contest_datetime(contest['starts_at'])} — {format_contest_datetime(contest['ends_at'])}"
    )
    return f"{contest['description_html']}\n\n{period}"


def build_criteria_html(contest) -> str:
    criteria = contest["criteria_html"] or "Отдельные критерии оценивания не указаны."
    return f"⚖️ <b>Критерии оценивания</b>\n\n{criteria}"


def default_success_message(title: str) -> str:
    return (
        "🍃 <b>Работа принята.</b>\n\n"
        f"Спасибо за участие в конкурсе «{html_escape(title)}». "
        "Мы получили вашу заявку и передали её организаторам."
    )


def allowed_categories(contest) -> list[str]:
    try:
        values = json.loads(contest["allowed_file_categories"] or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [value for value in values if value in FILE_CATEGORY_LABELS]


def format_allowed_categories(values: list[str]) -> str:
    return ", ".join(FILE_CATEGORY_LABELS[value] for value in values if value in FILE_CATEGORY_LABELS) or "нет"


def submission_mode_label(mode: str) -> str:
    return {"text": "текстом в боте", "files": "файлами", "both": "текстом или файлами"}.get(mode, mode)


def message_matches_allowed_file(message: Message, categories: list[str]) -> bool:
    selected = set(categories)
    if message.photo:
        return "images" in selected
    if message.audio:
        return "audio" in selected
    if message.video:
        return "video" in selected
    if not message.document or not message.document.file_name:
        return False
    suffix = PurePath(message.document.file_name.lower()).suffix
    return any(suffix in FILE_CATEGORY_EXTENSIONS[key] for key in selected)


def plain_from_html(value: str) -> str:
    return html_unescape(HTML_TAG_RE.sub("", value or ""))


def build_admin_contest_text(contest, *, submissions_count: int, channels: list) -> str:
    channel_text = ", ".join(row["title"] for row in channels) or "не проверяются"
    limit = contest["max_submissions"] if contest["max_submissions"] is not None else "без ограничения"
    destination = contest["destination_chat_title"] or str(contest["destination_chat_id"])
    if contest["destination_thread_id"] is not None:
        destination += f", топик {contest['destination_thread_id']}"
    status = "активен" if contest_timing_status(contest) in {"open", "upcoming"} else "завершён"
    return (
        f"🎨 Конкурс #{contest['id']}\n\n"
        f"Название: {contest['title']}\n"
        f"Статус: {status}\n"
        f"Начало: {format_contest_datetime(contest['starts_at'])}\n"
        f"Окончание: {format_contest_datetime(contest['ends_at'])}\n"
        f"Заявок: {submissions_count}\n"
        f"Лимит на участника: {limit}\n"
        f"Формат: {submission_mode_label(contest['submission_mode'])}\n"
        f"Файлы: {format_allowed_categories(allowed_categories(contest))}\n"
        f"Репост: {'нужен' if contest['require_repost'] else 'не нужен'}\n"
        f"Вопрос про ИИ: {'да' if contest['ask_ai'] else 'нет'}\n"
        f"Каналы: {channel_text}\n"
        f"Куда складывать: {destination}"
    )


def _normalize_channel_reference(raw: str) -> tuple[str | None, str | None]:
    token = raw.strip().strip(",;")
    if not token:
        return None, None
    if token.startswith("@"):
        username = token[1:]
    else:
        candidate = token if "://" in token else f"https://{token}"
        parsed = urlparse(candidate)
        if parsed.netloc.lower() not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
            return None, token
        parts = [part for part in parsed.path.split("/") if part]
        if not parts or parts[0] in {"+", "joinchat", "c"} or parts[0].startswith("+"):
            return None, token
        username = parts[0].lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,}", username):
        return None, token
    return f"@{username}", None


async def validate_required_channels(bot: Bot, raw_text: str) -> tuple[list[dict], list[str]]:
    refs = [item for item in re.split(r"[\s,;]+", raw_text.strip()) if item]
    if not refs:
        return [], ["список пуст"]
    bot_user = await bot.get_me()
    channels: list[dict] = []
    errors: list[str] = []
    seen_ids: set[int] = set()
    for raw in refs:
        reference, invalid = _normalize_channel_reference(raw)
        if invalid or reference is None:
            errors.append(f"{raw} — нужна публичная ссылка t.me или @username")
            continue
        try:
            chat = await bot.get_chat(reference)
            member = await bot.get_chat_member(chat.id, bot_user.id)
        except (TelegramBadRequest, TelegramForbiddenError):
            errors.append(f"{raw} — канал не найден или боту нет доступа")
            continue
        if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            errors.append(f"{raw} — бот не администратор")
            continue
        if chat.id in seen_ids:
            continue
        seen_ids.add(chat.id)
        username = chat.username or reference.lstrip("@")
        channels.append(
            {
                "channel_id": chat.id,
                "title": chat.title or f"@{username}",
                "username": username,
                "url": f"https://t.me/{username}",
            }
        )
    return channels, errors


async def missing_user_subscriptions(bot: Bot, contest_id: int, user_id: int) -> list:
    missing = []
    for channel in get_contest_channels(contest_id):
        try:
            member = await bot.get_chat_member(channel["channel_id"], user_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            missing.append(channel)
            continue
        if member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}:
            continue
        if member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False):
            continue
        missing.append(channel)
    return missing


def parse_topic_message_link(value: str, *, destination_chat_id: int, destination_username: str | None) -> int:
    candidate = value.strip()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.netloc.lower() not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        raise ValueError("Это не ссылка Telegram.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3:
        raise ValueError("Нужна ссылка на сообщение именно из топика.")
    if parts[0] == "c":
        if len(parts) < 4 or not parts[1].isdigit():
            raise ValueError("Не удалось разобрать ссылку закрытой группы.")
        linked_chat_id = int(f"-100{parts[1]}")
        topic_part = parts[2]
        if linked_chat_id != destination_chat_id:
            raise ValueError("Ссылка ведёт в другую группу.")
    else:
        if destination_username and parts[0].lower() != destination_username.lower():
            raise ValueError("Ссылка ведёт в другую группу.")
        topic_part = parts[1]
    if not topic_part.isdigit():
        raise ValueError("Не удалось определить топик.")
    return int(topic_part)


def build_submission_header_html(contest, user, data: dict, submission_format: str) -> str:
    username = f"@{user.username}" if user.username else "без username"
    lines = [
        "🍃 <b>Новая конкурсная заявка</b>",
        "",
        f"<b>Конкурс:</b> {html_escape(contest['title'])}",
        f"<b>Автор:</b> {html_escape(data.get('author') or '—')}",
        f"<b>Название:</b> {html_escape(data.get('title') or '—')}",
    ]
    if contest["require_repost"]:
        lines.append(f"<b>Репост:</b> {html_escape(data.get('repost_link') or '—')}")
    if contest["ask_ai"]:
        lines.append(f"<b>ИИ:</b> {html_escape(data.get('ai_link') or 'не использовался')}")
    lines.extend(
        [
            f"<b>Telegram:</b> {html_escape(user.full_name)} / {html_escape(username)} / ID: {user.id}",
            f"<b>Формат:</b> {html_escape(submission_format)}",
            f"<b>Дата:</b> {datetime.now(settings.MOSCOW_TZ).strftime('%d.%m.%Y %H:%M МСК')}",
        ]
    )
    return "\n".join(lines)


async def send_submission_to_destination(
    bot: Bot, *, contest, user, data: dict, submission_format: str,
    source_messages: list[tuple[int, int]],
) -> None:
    chat_id = int(contest["destination_chat_id"])
    thread_id = contest["destination_thread_id"]
    await bot.send_message(
        chat_id=chat_id,
        text=build_submission_header_html(contest, user, data, submission_format),
        parse_mode="HTML",
        **thread_kwargs(thread_id),
    )
    for source_chat_id, source_message_id in source_messages:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
            **thread_kwargs(thread_id),
        )
