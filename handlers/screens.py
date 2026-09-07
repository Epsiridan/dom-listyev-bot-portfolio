# -*- coding: utf-8 -*-
"""Безопасное обновление callback-экранов."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from services.telegram_utils import call_telegram_with_retry


async def safe_edit_or_answer(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    disable_web_page_preview: bool | None = None,
    parse_mode: str | None = None,
) -> None:
    """Изменить текущее callback-сообщение с fallback на новый ответ."""
    if callback.message is None:
        raise RuntimeError("CallbackQuery не содержит доступного сообщения")

    kwargs = {"reply_markup": reply_markup}
    if disable_web_page_preview is not None:
        kwargs["disable_web_page_preview"] = disable_web_page_preview
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode

    try:
        await call_telegram_with_retry(
            lambda: callback.message.edit_text(text, **kwargs),
            operation_name="edit callback screen",
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return

        try:
            await call_telegram_with_retry(
                lambda: callback.message.answer(text, **kwargs),
                operation_name="send callback screen fallback",
            )
        except TelegramBadRequest:
            if "parse_mode" not in kwargs:
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("parse_mode", None)
            await call_telegram_with_retry(
                lambda: callback.message.answer(text, **fallback_kwargs),
                operation_name="send callback screen without parse mode",
            )


async def send_content_screen(callback: CallbackQuery, key: str, *, reply_markup=None, values: dict[str, str] | None = None, suffix: str = "") -> None:
    """Показать контент в callback-сценарии, включая необязательное фото."""
    from services.content import get_content_block, send_content
    block = get_content_block(key)
    if not block.image_file_id or block.send_mode == "text":
        text=block.text
        for placeholder, value in (values or {}).items():
            text=text.replace("{" + placeholder + "}", value)
        await safe_edit_or_answer(callback, text + suffix, reply_markup=reply_markup)
    else:
        await send_content(callback.message, key, reply_markup=reply_markup, values=values, suffix=suffix)
