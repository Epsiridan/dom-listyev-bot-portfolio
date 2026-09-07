# -*- coding: utf-8 -*-
"""Общие Telegram-утилиты: повторы API, топики, текстовые чанки и callback_data."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter

TELEGRAM_SAFE_TEXT_CHUNK = 3900
TELEGRAM_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.5)
TELEGRAM_MAX_RETRY_AFTER = 5.0

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def call_telegram_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    operation_name: str,
    retry_delays: tuple[float, ...] = TELEGRAM_RETRY_DELAYS,
) -> T:
    """Повторить вызов только при временной сетевой ошибке Telegram."""
    total_attempts = len(retry_delays) + 1
    for attempt in range(total_attempts):
        try:
            return await operation()
        except (TelegramNetworkError, TelegramRetryAfter) as error:
            if attempt >= len(retry_delays):
                logger.error(
                    "Telegram operation failed after %s attempts: %s",
                    total_attempts,
                    operation_name,
                )
                raise

            retry_after = getattr(error, "retry_after", None)
            delay = (
                retry_delays[attempt]
                if retry_after is None
                else min(max(float(retry_after), 0.0), TELEGRAM_MAX_RETRY_AFTER)
            )
            logger.warning(
                "Temporary Telegram error; retrying %s (%s/%s) in %.1fs: %s",
                operation_name,
                attempt + 1,
                total_attempts,
                delay,
                error,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("Недостижимая ветка повторов Telegram API")


def thread_kwargs(thread_id: int | None) -> dict[str, int]:
    """Не передавать message_thread_id, если топик не настроен."""
    if thread_id is None:
        return {}
    return {"message_thread_id": thread_id}


def split_text_chunks(
    text: str,
    *,
    chunk_size: int = TELEGRAM_SAFE_TEXT_CHUNK,
) -> list[str]:
    """Разбить текст на безопасные для Telegram куски."""
    if chunk_size <= 0:
        raise ValueError("chunk_size должен быть положительным")
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [text]


def callback_value(callback_data: str | None) -> str:
    """Достать непустую часть после первого двоеточия."""
    if not callback_data or ":" not in callback_data:
        raise ValueError(f"Некорректный callback_data: {callback_data!r}")
    _, value = callback_data.split(":", maxsplit=1)
    if not value:
        raise ValueError(f"Пустое значение callback_data: {callback_data!r}")
    return value


def callback_int_id(callback_data: str | None) -> int:
    """Достать числовой ID из callback_data."""
    return int(callback_value(callback_data))
