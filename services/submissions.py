# -*- coding: utf-8 -*-
"""Передача конкурсных заявок организаторам."""

from datetime import datetime

from aiogram import Bot
from aiogram.types import Message

from config import settings
from services.telegram_utils import split_text_chunks, thread_kwargs


def user_label(user) -> str:
    """Собрать человекочитаемую подпись Telegram-пользователя."""
    username = f"@{user.username}" if user and user.username else "без username"
    full_name = user.full_name if user else "неизвестно"
    user_id = user.id if user else "неизвестно"
    return f"{full_name} / {username} / ID: {user_id}"


def build_submission_header(user, data: dict, submission_format: str) -> str:
    """Сформировать шапку заявки для админского чата."""
    now = datetime.now(settings.MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")
    ai_value = data.get("ai_link") or "не использовался"
    return (
        "🍃 Новая заявка на конкурс\n\n"
        "Конкурс: ЭХО // мерцание\n\n"
        f"Автор: {data.get('author')}\n"
        f"Название: {data.get('title')}\n"
        f"Репост: {data.get('repost_link')}\n"
        f"ИИ: {ai_value}\n"
        f"Telegram: {user_label(user)}\n"
        f"Дата: {now}\n"
        f"Формат: {submission_format}"
    )


async def send_long_text(
    bot: Bot,
    chat_id: int,
    text: str,
    message_thread_id: int | None = None,
) -> None:
    """Отправить длинный текст частями меньше лимита Telegram."""
    chunks = split_text_chunks(text)
    for index, chunk in enumerate(chunks, start=1):
        prefix = ""
        if len(chunks) > 1:
            prefix = f"Часть {index}/{len(chunks)}\n\n"
        await bot.send_message(
            chat_id=chat_id,
            text=prefix + chunk,
            **thread_kwargs(message_thread_id),
        )


async def send_submission_to_admin_chat(
    bot: Bot,
    message: Message,
    data: dict,
    submission_format: str,
    user=None,
) -> None:
    """Передать организаторам шапку заявки и саму работу."""
    await bot.send_message(
        chat_id=settings.ADMIN_GROUP_ID,
        text=build_submission_header(user or message.from_user, data, submission_format),
        **thread_kwargs(settings.ADMIN_CONTESTS_THREAD_ID),
    )

    if submission_format == "текст":
        text_parts = data.get("text_parts", [])
        work_text = "\n\n".join(text_parts).strip()
        await send_long_text(
            bot=bot,
            chat_id=settings.ADMIN_GROUP_ID,
            text=f"Текст работы:\n\n{work_text}",
            message_thread_id=settings.ADMIN_CONTESTS_THREAD_ID,
        )
    else:
        await bot.copy_message(
            chat_id=settings.ADMIN_GROUP_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            **thread_kwargs(settings.ADMIN_CONTESTS_THREAD_ID),
        )


def document_is_allowed(message: Message) -> bool:
    """Разрешены только текстовые форматы, которые заявлены в правилах конкурса."""
    if not message.document or not message.document.file_name:
        return False
    filename = message.document.file_name.lower()
    return filename.endswith(".txt") or filename.endswith(".docx")
