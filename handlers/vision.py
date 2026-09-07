# -*- coding: utf-8 -*-
"""Команда /опознай (также /опознай@DomListyevBot) для доступного описания изображений."""

from __future__ import annotations

import io
import logging
import mimetypes
import re
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from openai import OpenAIError

from services.community import user_is_member
from services.telegram_utils import split_text_chunks
from services.vision import VisionUnavailableError, describe_image

logger = logging.getLogger(__name__)
router = Router()

VISION_COMMAND_PATTERN = (
    r"(?is)^/опознай(?:@DomListyevBot)?(?:\s+(?P<request>.*?))?\s*$"
)
VISION_COMMAND_RE = re.compile(VISION_COMMAND_PATTERN)
VISION_FILTER = F.text.regexp(VISION_COMMAND_PATTERN) | F.caption.regexp(
    VISION_COMMAND_PATTERN
)
SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


@dataclass(frozen=True)
class TelegramImage:
    """Ссылка на изображение в Telegram и сообщение, к которому нужно ответить."""

    file_id: str
    mime_type: str
    source_message: Message


def extract_user_request(message: Message) -> str | None:
    """Достать необязательный вопрос после кириллической команды."""
    raw = message.text or message.caption or ""
    match = VISION_COMMAND_RE.fullmatch(raw.strip())
    if not match:
        return None
    request = (match.group("request") or "").strip()
    return request or None


def _document_mime_type(message: Message) -> str | None:
    document = message.document
    if document is None:
        return None
    mime_type = (document.mime_type or "").lower()
    if not mime_type and document.file_name:
        mime_type = (mimetypes.guess_type(document.file_name)[0] or "").lower()
    return mime_type if mime_type in SUPPORTED_IMAGE_MIME_TYPES else None


def image_from_message(message: Message | None) -> TelegramImage | None:
    """Выбрать самое качественное фото или поддерживаемый графический документ."""
    if message is None:
        return None
    if message.photo:
        return TelegramImage(
            file_id=message.photo[-1].file_id,
            mime_type="image/jpeg",
            source_message=message,
        )
    mime_type = _document_mime_type(message)
    if mime_type and message.document:
        return TelegramImage(
            file_id=message.document.file_id,
            mime_type=mime_type,
            source_message=message,
        )
    return None


def find_request_image(message: Message) -> TelegramImage | None:
    """Поддержать изображение с подписью-командой и ответ команды на изображение."""
    return image_from_message(message) or image_from_message(message.reply_to_message)


async def download_image(bot: Bot, image: TelegramImage) -> bytes:
    """Скачать изображение только в оперативную память."""
    buffer = io.BytesIO()
    await bot.download(image.file_id, destination=buffer)
    return buffer.getvalue()


async def reply_with_chunks(target: Message, text: str) -> None:
    """Ответить на исходное изображение, не упираясь в лимит текста Telegram."""
    for chunk in split_text_chunks(text):
        try:
            await target.reply(chunk)
        except TelegramBadRequest:
            await target.answer(chunk)


async def _handle_vision_request(message: Message, bot: Bot) -> None:
    requester = message.from_user
    if requester is None or requester.is_bot:
        await message.answer(
            "Не могу определить автора сообщения и проверить его участие в Доме Листьев."
        )
        return
    if not await user_is_member(bot, requester.id):
        await message.answer(
            "Эта функция доступна только участникам основной группы «Дом Листьев»."
        )
        return

    image = find_request_image(message)
    if image is None:
        await message.answer(
            "Отправьте изображение с подписью /опознай "
            "или ответьте этой командой на сообщение с изображением."
        )
        return

    try:
        image_bytes = await download_image(bot, image)
        description = await describe_image(
            image_bytes,
            mime_type=image.mime_type,
            user_id=requester.id,
            user_request=extract_user_request(message),
        )
        await reply_with_chunks(image.source_message, description)
    except (OpenAIError, TelegramAPIError, OSError, VisionUnavailableError, ValueError):
        logger.exception(
            "Image recognition failed for user_id=%s chat_id=%s",
            requester.id,
            message.chat.id,
        )
        await message.answer(
            "Не получилось описать изображение. Попробуйте отправить его ещё раз чуть позже."
        )


@router.message(VISION_FILTER)
async def recognize_message_image(message: Message, bot: Bot) -> None:
    """Обработать команду в личке, группе или супергруппе."""
    await _handle_vision_request(message, bot)


@router.channel_post(VISION_FILTER)
async def recognize_channel_image(message: Message, bot: Bot) -> None:
    """Обработать пост канала, если Telegram передал реального автора."""
    await _handle_vision_request(message, bot)
