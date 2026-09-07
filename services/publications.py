# -*- coding: utf-8 -*-
"""Сервис предложки и публикаций в канал.

Здесь собрана логика, которая не зависит от конкретного handler-а: извлечение
текста/медиа из Telegram-сообщений, сборка карточек модерации, публикация в
канал и уведомления авторов.
"""

import asyncio
import re
from datetime import datetime
from html import escape as html_escape
from html import unescape as html_unescape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from config import settings
from keyboards import proposed_post_review_keyboard
from texts import PROPOSED_POST_ADMIN_CONTACTS_TEXT
from services.database import (
    create_proposed_post,
    get_due_proposed_posts,
    get_proposed_post,
    mark_proposed_post_published,
    set_proposed_post_review_message,
)
from services.submissions import user_label
from services.telegram_utils import (
    TELEGRAM_SAFE_TEXT_CHUNK,
    split_text_chunks,
    thread_kwargs,
)


TRIGGER_RE = re.compile(r"@DomListyevBot\s+новый\s+лист", flags=re.IGNORECASE)
TEXT_FORMAT_PLAIN = "plain"
TEXT_FORMAT_HTML = "html"
PUBLICATION_HASHTAG = "#Творчество@house_of_the_leaves"
TELEGRAM_MEDIA_CAPTION_LIMIT = 1000
HTML_TAG_RE = re.compile(r"<[^>]+>")
SKIP_CREATIVE_GROUP_VALUES = {
    "без группы",
    "без творческой группы",
    "нет",
    "не хочу",
    "не прикреплять",
    "пропустить",
    "-",
    "—",
}


# --- Нормализация текста, разметки и данных Telegram-сообщения --------------

def is_html_text_format(text_format: str | None) -> bool:
    """Проверить, можно ли отправлять текст с parse_mode=HTML."""
    return text_format == TEXT_FORMAT_HTML


def parse_mode_for_text_format(text_format: str | None) -> str | None:
    """Преобразовать внутренний формат текста в parse_mode Bot API."""
    if is_html_text_format(text_format):
        return "HTML"
    return None


def _post_text_format(post) -> str:
    """Безопасно получить формат текста из sqlite.Row/dict."""
    try:
        return post["text_format"] or TEXT_FORMAT_PLAIN
    except (KeyError, IndexError):
        return TEXT_FORMAT_PLAIN


def _post_creative_group_format(post) -> str:
    """Безопасно получить формат поля творческой группы."""
    try:
        return post["creative_group_format"] or TEXT_FORMAT_PLAIN
    except (KeyError, IndexError):
        return TEXT_FORMAT_PLAIN


def _post_debug_id(post) -> object:
    """ID для логов: не должен падать даже на неполной записи."""
    try:
        return post["id"]
    except (KeyError, IndexError):
        return "unknown"


def _html_value(value: object, fallback: str = "неизвестно") -> str:
    """Экранировать значение, которое попадёт в HTML-сообщение."""
    text = str(value) if value else fallback
    return html_escape(text)


def _plain_value_from_html(value: object) -> str:
    """Получить читаемый plain-text из небольшого Telegram HTML-фрагмента."""
    return html_unescape(HTML_TAG_RE.sub("", str(value)))


def _creative_group_value_for_html(
    value: object,
    creative_group_format: str | None,
    *,
    fallback: str = "не прикреплена",
) -> str:
    """Подготовить творческую группу для сообщения с parse_mode=HTML."""
    if not value:
        return html_escape(fallback)
    if creative_group_format == TEXT_FORMAT_HTML:
        return str(value)
    return html_escape(str(value))


def _creative_group_value_for_plain(
    value: object,
    creative_group_format: str | None,
    *,
    fallback: str = "не прикреплена",
) -> str:
    """Подготовить творческую группу для сообщения без parse_mode."""
    if not value:
        return fallback
    if creative_group_format == TEXT_FORMAT_HTML:
        return _plain_value_from_html(value)
    return str(value)


def has_new_leaf_trigger(text: str | None) -> bool:
    """Понять, содержит ли сообщение команду `@DomListyevBot новый лист`."""
    return bool(text and TRIGGER_RE.search(text))


def strip_new_leaf_trigger(text: str) -> str:
    """Убрать триггер из текста, если пользователь написал пост в той же строке."""
    return TRIGGER_RE.sub("", text, count=1).strip()


def normalize_creative_group(value: str | None) -> str | None:
    """Превратить пустые/служебные ответы про группу в None."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.lower() in SKIP_CREATIVE_GROUP_VALUES:
        return None
    return normalized


def extract_creative_group_from_message(message: Message) -> tuple[str | None, str]:
    """Достать группу из сообщения, сохранив привязанные к тексту ссылки."""
    plain_text = (message.text or "").strip()
    if normalize_creative_group(plain_text) is None:
        return None, TEXT_FORMAT_PLAIN

    # Telegram хранит кликабельные ссылки/форматирование в entities, а aiogram
    # превращает их в безопасный Bot API HTML. Так можно опубликовать строку
    # «Творческая группа» с текстовой ссылкой, а не только голый URL.
    html_text = (getattr(message, "html_text", None) or plain_text).strip()
    return html_text, TEXT_FORMAT_HTML


def build_telegram_message_link(message: Message) -> str | None:
    """Собрать публичную или внутреннюю ссылку на исходное сообщение."""
    if message.chat.username:
        return f"https://t.me/{message.chat.username}/{message.message_id}"

    if message.chat.id < -1000000000000:
        internal_id = abs(message.chat.id) - 1000000000000
        return f"https://t.me/c/{internal_id}/{message.message_id}"

    return None


def extract_media_data(message: Message) -> dict[str, str | None]:
    """Достать поддерживаемое медиа, которое можно приложить к публикации."""
    if message.photo:
        photo = message.photo[-1]
        return {
            "media_type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_name": None,
        }

    if message.audio:
        return {
            "media_type": "audio",
            "file_id": message.audio.file_id,
            "file_unique_id": message.audio.file_unique_id,
            "file_name": message.audio.file_name,
        }

    if message.document:
        mime_type = message.document.mime_type or ""
        if mime_type.startswith("image/") or mime_type.startswith("audio/"):
            return {
                "media_type": "document",
                "file_id": message.document.file_id,
                "file_unique_id": message.document.file_unique_id,
                "file_name": message.document.file_name,
            }

    return {
        "media_type": None,
        "file_id": None,
        "file_unique_id": None,
        "file_name": None,
    }


def extract_publication_text(message: Message, *, remove_trigger: bool = False) -> str:
    # Telegram keeps bold/italic/links separately in entities. Aiogram's
    # html_text/html_caption converts those entities to Bot API HTML and escapes
    # plain user text, so we can safely store and re-send it with parse_mode=HTML.
    text = (
        getattr(message, "html_text", None)
        or getattr(message, "html_caption", None)
        or message.text
        or message.caption
        or ""
    )
    if remove_trigger:
        text = strip_new_leaf_trigger(text)
    return text.strip()


def build_submission_data_from_message(
    message: Message,
    *,
    text: str,
    text_format: str = TEXT_FORMAT_HTML,
    creative_group: str | None = None,
    creative_group_format: str = TEXT_FORMAT_PLAIN,
) -> dict[str, Any]:
    """Нормализовать Telegram-сообщение в словарь для записи proposed_posts."""
    media_data = extract_media_data(message)
    return {
        "source_chat_id": message.chat.id,
        "source_message_id": message.message_id,
        "source_thread_id": message.message_thread_id,
        "source_link": build_telegram_message_link(message),
        "user_id": message.from_user.id if message.from_user else None,
        "username": message.from_user.username if message.from_user else None,
        "full_name": message.from_user.full_name if message.from_user else None,
        "author_label": user_label(message.from_user),
        "publish_author": False,
        "creative_group": creative_group,
        "creative_group_format": creative_group_format if creative_group else TEXT_FORMAT_PLAIN,
        "text": text,
        "text_format": text_format,
        **media_data,
    }


def build_publication_text(post) -> str:
    """Собрать финальный текст публикации с футером и рубричным хэштегом."""
    footer: list[str] = []
    text_format = _post_text_format(post)
    creative_group_format = _post_creative_group_format(post)
    author = _publication_author_from_post(post)
    if author:
        if is_html_text_format(text_format):
            footer.append(f"Автор: {html_escape(author)}")
        else:
            footer.append(f"Автор: {author}")
    if post["creative_group"]:
        if is_html_text_format(text_format):
            footer.append(
                "🍃 Творческая группа: "
                f"{_creative_group_value_for_html(post['creative_group'], creative_group_format)}"
            )
        else:
            footer.append(
                "🍃 Творческая группа: "
                f"{_creative_group_value_for_plain(post['creative_group'], creative_group_format)}"
            )

    # Две пустые строки визуально отделяют произведение от служебного футера.
    footer.append(PUBLICATION_HASHTAG)
    return f"{post['text']}\n\n\n" + "\n\n".join(footer)


def format_scheduled_for(value: str | None) -> str:
    """Форматировать дату очереди в привычном виде для админов и авторов."""
    if not value:
        return "без даты"
    try:
        scheduled_for = datetime.fromisoformat(value).astimezone(settings.MOSCOW_TZ)
    except ValueError:
        return value
    return scheduled_for.strftime("%d.%m.%Y %H:%M МСК")


def _format_user_from_post(post) -> str:
    """Подпись автора для админской карточки."""
    username = f"@{post['username']}" if post["username"] else "без username"
    full_name = post["full_name"] or "неизвестно"
    user_id = post["user_id"] or "неизвестно"
    return f"{full_name} / {username} / ID: {user_id}"


def _publication_author_from_post(post) -> str | None:
    """Вернуть автора для футера публикации, если пользователь разрешил."""
    if not post["publish_author"]:
        return None
    if post["username"]:
        return f"@{post['username']}"
    return post["full_name"]


def build_review_summary_from_data(post_id: int, data: dict[str, Any]) -> str:
    """Собрать служебную часть карточки модерации без текста публикации."""
    if is_html_text_format(data.get("text_format")):
        source_link = data.get("source_link") or "ссылка недоступна"
        creative_group = _creative_group_value_for_html(
            data.get("creative_group"),
            data.get("creative_group_format"),
        )
        media_label = data.get("media_type") or "нет"
        author_publication = "да" if data.get("publish_author") else "нет"
        now = datetime.now(settings.MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")
        return (
            f"🍃 Новый лист в предложку #{post_id}\n\n"
            f"Автор: {_html_value(data.get('author_label'))}\n"
            f"Творческая группа: {creative_group}\n"
            f"Автор в публикации: {author_publication}\n"
            f"Источник: {html_escape(source_link)}\n"
            f"Дата: {now}\n"
            f"Медиа: {html_escape(media_label)}"
        )

    source_link = data.get("source_link") or "ссылка недоступна"
    creative_group = _creative_group_value_for_plain(
        data.get("creative_group"),
        data.get("creative_group_format"),
    )
    media_label = data.get("media_type") or "нет"
    author_publication = "да" if data.get("publish_author") else "нет"
    now = datetime.now(settings.MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")
    return (
        f"🍃 Новый лист в предложку #{post_id}\n\n"
        f"Автор: {data.get('author_label', 'неизвестно')}\n"
        f"Творческая группа: {creative_group}\n"
        f"Автор в публикации: {author_publication}\n"
        f"Источник: {source_link}\n"
        f"Дата: {now}\n"
        f"Медиа: {media_label}"
    )


def build_review_text_from_data(post_id: int, data: dict[str, Any]) -> str:
    """Собрать полную карточку модерации сразу после создания записи."""
    return (
        f"{build_review_summary_from_data(post_id, data)}\n\n"
        f"Текст для публикации:\n\n{data['text']}"
    )


def build_review_summary_from_post(post) -> str:
    """Собрать служебную часть карточки сохранённого поста без его текста."""
    if is_html_text_format(_post_text_format(post)):
        source_link = post["source_link"] or "ссылка недоступна"
        creative_group = _creative_group_value_for_html(
            post["creative_group"],
            _post_creative_group_format(post),
        )
        media_label = post["media_type"] or "нет"
        author_publication = "да" if post["publish_author"] else "нет"
        return (
            f"🍃 Новый лист в предложку #{post['id']}\n\n"
            f"Автор: {html_escape(_format_user_from_post(post))}\n"
            f"Творческая группа: {creative_group}\n"
            f"Автор в публикации: {author_publication}\n"
            f"Источник: {html_escape(source_link)}\n"
            f"Медиа: {html_escape(media_label)}"
        )

    source_link = post["source_link"] or "ссылка недоступна"
    creative_group = _creative_group_value_for_plain(
        post["creative_group"],
        _post_creative_group_format(post),
    )
    media_label = post["media_type"] or "нет"
    author_publication = "да" if post["publish_author"] else "нет"
    return (
        f"🍃 Новый лист в предложку #{post['id']}\n\n"
        f"Автор: {_format_user_from_post(post)}\n"
        f"Творческая группа: {creative_group}\n"
        f"Автор в публикации: {author_publication}\n"
        f"Источник: {source_link}\n"
        f"Медиа: {media_label}"
    )


def build_review_text_from_post(post) -> str:
    """Собрать полную карточку модерации из сохранённой записи."""
    return (
        f"{build_review_summary_from_post(post)}\n\n"
        f"Текст для публикации:\n\n{post['text']}"
    )


def build_rejected_summary_from_post(post) -> str:
    """Собрать служебную часть сообщения для архива отклонённых листов."""
    if is_html_text_format(_post_text_format(post)):
        source_line = f"Источник: {html_escape(post['source_link'])}\n" if post["source_link"] else ""
        creative_group_line = (
            "Творческая группа: "
            f"{_creative_group_value_for_html(post['creative_group'], _post_creative_group_format(post))}\n"
            if post["creative_group"]
            else ""
        )
        return (
            f"❌ Отклонённый лист #{post['id']}\n\n"
            f"{source_line}"
            f"{creative_group_line}"
        )

    source_line = f"Источник: {post['source_link']}\n" if post["source_link"] else ""
    creative_group_line = (
        "Творческая группа: "
        f"{_creative_group_value_for_plain(post['creative_group'], _post_creative_group_format(post))}\n"
        if post["creative_group"]
        else ""
    )
    return (
        f"❌ Отклонённый лист #{post['id']}\n\n"
        f"{source_line}"
        f"{creative_group_line}"
    ).rstrip()


def build_rejected_text_from_post(post) -> str:
    """Собрать полное сообщение для архива отклонённых листов."""
    return (
        f"{build_rejected_summary_from_post(post).rstrip()}\n\n"
        f"Текст:\n\n{post['text']}"
    )


# --- Отправка модератору и публикация в канал ------------------------------

async def send_text_chunks(
    bot: Bot,
    *,
    chat_id: int,
    text: str,
    parse_mode: str | None = None,
    message_thread_id: int | None = None,
) -> list[int]:
    """Отправить длинный текст безопасными частями и вернуть ID сообщений."""
    chunks = split_text_chunks(text)
    message_ids: list[int] = []
    for index, chunk in enumerate(chunks, start=1):
        prefix = ""
        if len(chunks) > 1:
            prefix = f"Часть {index}/{len(chunks)}\n\n"
        message_text = prefix + chunk
        try:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=parse_mode,
                **thread_kwargs(message_thread_id),
            )
        except TelegramBadRequest:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                **thread_kwargs(message_thread_id),
            )
        message_ids.append(sent.message_id)
    return message_ids


async def send_media_preview(bot: Bot, *, chat_id: int, post_id: int, data: dict[str, Any]) -> None:
    """Отправить медиа-превью в админскую предложку рядом с карточкой."""
    media_type = data.get("media_type")
    file_id = data.get("file_id")
    if not media_type or not file_id:
        return

    caption = f"Медиа к листу #{post_id}"
    kwargs = thread_kwargs(settings.ADMIN_PROPOSALS_THREAD_ID)
    if media_type == "photo":
        await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, **kwargs)
    elif media_type == "audio":
        await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption, **kwargs)
    else:
        await bot.send_document(chat_id=chat_id, document=file_id, caption=caption, **kwargs)


async def _send_body_safely(
    bot: Bot,
    *,
    chat_id: int,
    text: str,
    parse_mode: str | None,
    message_thread_id: int | None,
) -> None:
    """Отправить длинное тело отдельно, сохранив HTML при возможности."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            **thread_kwargs(message_thread_id),
        )
    except TelegramBadRequest:
        plain_text = _plain_value_from_html(text) if parse_mode == "HTML" else text
        await send_text_chunks(
            bot,
            chat_id=chat_id,
            text=plain_text,
            message_thread_id=message_thread_id,
        )


async def _send_review_card_parts(
    bot: Bot,
    *,
    chat_id: int,
    message_thread_id: int | None,
    post_id: int,
    summary_text: str,
    body_text: str,
    parse_mode: str | None,
) -> Message:
    """Отправить короткую карточку целиком, а длинную — двумя сообщениями."""
    thread = thread_kwargs(message_thread_id)
    review_text = f"{summary_text}\n\nТекст для публикации:\n\n{body_text}"
    keyboard = proposed_post_review_keyboard(post_id)

    if len(review_text) <= TELEGRAM_SAFE_TEXT_CHUNK:
        return await bot.send_message(
            chat_id=chat_id,
            text=review_text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
            **thread,
        )

    sent = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{summary_text}\n\n"
            "Текст для публикации отправлен следующим сообщением."
        ),
        parse_mode=parse_mode,
        reply_markup=keyboard,
        **thread,
    )
    await _send_body_safely(
        bot,
        chat_id=chat_id,
        text=body_text,
        parse_mode=parse_mode,
        message_thread_id=message_thread_id,
    )
    return sent


async def send_review_card(bot: Bot, *, post_id: int, data: dict[str, Any]) -> Message:
    """Отправить новую админскую карточку, не превышая лимит Telegram."""
    return await _send_review_card_parts(
        bot,
        chat_id=settings.ADMIN_GROUP_ID,
        message_thread_id=settings.ADMIN_PROPOSALS_THREAD_ID,
        post_id=post_id,
        summary_text=build_review_summary_from_data(post_id, data),
        body_text=str(data["text"]),
        parse_mode=parse_mode_for_text_format(data.get("text_format")),
    )


async def send_stored_review_card(
    bot: Bot,
    *,
    chat_id: int,
    message_thread_id: int | None,
    post,
) -> Message:
    """Безопасно повторно показать сохранённый пост после правки или отмены."""
    return await _send_review_card_parts(
        bot,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        post_id=int(post["id"]),
        summary_text=build_review_summary_from_post(post),
        body_text=str(post["text"]),
        parse_mode=parse_mode_for_text_format(_post_text_format(post)),
    )


async def send_rejected_post_to_archive(bot: Bot, post) -> None:
    """Безопасно отправить отклонённый пост в архив, включая длинный текст."""
    parse_mode = parse_mode_for_text_format(_post_text_format(post))
    rejected_text = build_rejected_text_from_post(post)
    if len(rejected_text) <= TELEGRAM_SAFE_TEXT_CHUNK:
        await bot.send_message(
            chat_id=settings.ADMIN_GROUP_ID,
            text=rejected_text,
            parse_mode=parse_mode,
            **thread_kwargs(settings.ADMIN_REJECTS_THREAD_ID),
        )
        return

    await bot.send_message(
        chat_id=settings.ADMIN_GROUP_ID,
        text=(
            f"{build_rejected_summary_from_post(post).rstrip()}\n\n"
            "Текст отклонённого листа отправлен следующим сообщением."
        ),
        parse_mode=parse_mode,
        **thread_kwargs(settings.ADMIN_REJECTS_THREAD_ID),
    )
    await _send_body_safely(
        bot,
        chat_id=settings.ADMIN_GROUP_ID,
        text=str(post["text"]),
        parse_mode=parse_mode,
        message_thread_id=settings.ADMIN_REJECTS_THREAD_ID,
    )


async def create_review_for_submission_data(bot: Bot, data: dict[str, Any]) -> int:
    """Создать запись предложки и отправить карточку модерации админам."""
    creative_group = normalize_creative_group(data.get("creative_group"))
    creative_group_format = (
        data.get("creative_group_format", TEXT_FORMAT_PLAIN)
        if creative_group
        else TEXT_FORMAT_PLAIN
    )
    post_id = create_proposed_post(
        source_chat_id=data["source_chat_id"],
        source_message_id=data["source_message_id"],
        source_thread_id=data.get("source_thread_id"),
        source_link=data.get("source_link"),
        user_id=data.get("user_id"),
        username=data.get("username"),
        full_name=data.get("full_name"),
        publish_author=bool(data.get("publish_author")),
        creative_group=creative_group,
        creative_group_format=creative_group_format,
        text=data["text"],
        text_format=data.get("text_format", TEXT_FORMAT_PLAIN),
        media_type=data.get("media_type"),
        file_id=data.get("file_id"),
        file_unique_id=data.get("file_unique_id"),
        file_name=data.get("file_name"),
    )
    data = {
        **data,
        "creative_group": creative_group,
        "creative_group_format": creative_group_format,
    }
    sent = await send_review_card(bot, post_id=post_id, data=data)
    set_proposed_post_review_message(
        post_id,
        admin_chat_id=sent.chat.id,
        admin_message_id=sent.message_id,
        review_thread_id=sent.message_thread_id,
    )
    await send_media_preview(
        bot,
        chat_id=settings.ADMIN_GROUP_ID,
        post_id=post_id,
        data=data,
    )
    return post_id


async def create_review_for_new_leaf(
    bot: Bot,
    source_message: Message,
    text: str,
    creative_group: str | None = None,
) -> int:
    """Совместимость для создания предложки из исходного Telegram-сообщения."""
    data = build_submission_data_from_message(
        source_message,
        text=text,
        creative_group=creative_group,
    )
    return await create_review_for_submission_data(bot, data)


async def _send_publication_media(bot: Bot, *, chat_id: int, post, text: str) -> list[int]:
    """Опубликовать текст с медиа или без него, учитывая лимит caption."""
    media_type = post["media_type"]
    file_id = post["file_id"]
    parse_mode = parse_mode_for_text_format(_post_text_format(post))
    if not media_type or not file_id:
        return await send_text_chunks(bot, chat_id=chat_id, text=text, parse_mode=parse_mode)

    if len(text) <= TELEGRAM_MEDIA_CAPTION_LIMIT:
        try:
            if media_type == "photo":
                sent = await bot.send_photo(
                    chat_id=chat_id,
                    photo=file_id,
                    caption=text,
                    parse_mode=parse_mode,
                )
            elif media_type == "audio":
                sent = await bot.send_audio(
                    chat_id=chat_id,
                    audio=file_id,
                    caption=text,
                    parse_mode=parse_mode,
                )
            else:
                sent = await bot.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=text,
                    parse_mode=parse_mode,
                )
        except TelegramBadRequest:
            if media_type == "photo":
                sent = await bot.send_photo(chat_id=chat_id, photo=file_id, caption=text)
            elif media_type == "audio":
                sent = await bot.send_audio(chat_id=chat_id, audio=file_id, caption=text)
            else:
                sent = await bot.send_document(chat_id=chat_id, document=file_id, caption=text)
        return [sent.message_id]

    if media_type == "photo":
        sent = await bot.send_photo(chat_id=chat_id, photo=file_id)
    elif media_type == "audio":
        sent = await bot.send_audio(chat_id=chat_id, audio=file_id)
    else:
        sent = await bot.send_document(chat_id=chat_id, document=file_id)
    text_message_ids = await send_text_chunks(
        bot,
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
    )
    return [sent.message_id, *text_message_ids]


async def notify_author_about_approval(bot: Bot, post) -> bool:
    """Сообщить автору, что лист одобрен, и показать будущую публикацию."""
    try:
        user_id = post["user_id"]
        if not user_id:
            print(f"approval notification skipped: post #{_post_debug_id(post)} has no user_id")
            return False

        await bot.send_message(
            chat_id=user_id,
            text=(
                "🍃 Ваш лист одобрен — Дом шуршит страницами.\n\n"
                f"Публикация запланирована на {format_scheduled_for(post['scheduled_for'])}.\n\n"
                "Ниже показываю версию, которая выйдет в канале."
            ),
        )
        await _send_publication_media(
            bot,
            chat_id=user_id,
            post=post,
            text=build_publication_text(post),
        )
        return True
    except Exception as error:
        print(f"approval notification failed for post #{_post_debug_id(post)}: {error!r}")
        return False


async def notify_author_about_queue_shift(bot: Bot, post) -> bool:
    """Сообщить автору, что его публикация сдвинулась в очереди."""
    try:
        user_id = post["user_id"]
        if not user_id:
            print(f"queue shift notification skipped: post #{_post_debug_id(post)} has no user_id")
            return False

        old_scheduled_for = post.get("old_scheduled_for") if isinstance(post, dict) else None
        old_line = ""
        if old_scheduled_for:
            old_line = f"\nБыло: {format_scheduled_for(old_scheduled_for)}"

        await bot.send_message(
            chat_id=user_id,
            text=(
                "🍃 Маленькое движение в очереди.\n\n"
                "Дата публикации вашего листа изменилась."
                f"{old_line}\n"
                f"Теперь: {format_scheduled_for(post['scheduled_for'])}."
            ),
        )
        return True
    except Exception as error:
        print(f"queue shift notification failed for post #{_post_debug_id(post)}: {error!r}")
        return False


async def notify_author_about_queue_removal(bot: Bot, post) -> bool:
    """Сообщить автору, что лист снят с очереди публикаций."""
    try:
        user_id = post["user_id"]
        if not user_id:
            print(f"queue removal notification skipped: post #{_post_debug_id(post)} has no user_id")
            return False

        await bot.send_message(
            chat_id=user_id,
            text=(
                "🍂 Ваш лист снят с очереди публикаций.\n\n"
                f"Он был запланирован на {format_scheduled_for(post['scheduled_for'])}.\n\n"
                "Если хотите узнать причину, напишите администратору: "
                f"{PROPOSED_POST_ADMIN_CONTACTS_TEXT}."
            ),
        )
        return True
    except Exception as error:
        print(f"queue removal notification failed for post #{_post_debug_id(post)}: {error!r}")
        return False


async def publish_proposed_post_now(bot: Bot, post_id: int) -> int | None:
    """Опубликовать лист немедленно и пометить его опубликованным."""
    post = get_proposed_post(post_id)
    if post is None:
        return None

    message_ids = await _send_publication_media(
        bot,
        chat_id=settings.PUBLIC_CHANNEL_ID,
        post=post,
        text=build_publication_text(post),
    )
    first_message_id = message_ids[0] if message_ids else None
    mark_proposed_post_published(
        post_id,
        publication_chat_id=settings.PUBLIC_CHANNEL_ID,
        publication_message_id=first_message_id,
    )
    return first_message_id


async def publish_due_proposed_posts(bot: Bot) -> None:
    """Опубликовать несколько листов, чей слот уже наступил."""
    for post in get_due_proposed_posts(limit=3):
        await publish_proposed_post_now(bot, post["id"])


async def publication_loop(bot: Bot) -> None:
    """Бесконечный планировщик публикаций; запускается из bot.py."""
    while True:
        try:
            await publish_due_proposed_posts(bot)
        except Exception as error:
            print(f"publication_loop error: {error!r}")
        await asyncio.sleep(60)
