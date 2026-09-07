# -*- coding: utf-8 -*-
"""Операции Telegram-группы сообщества."""

from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatInviteLink

from config import settings


async def user_is_member(bot: Bot, user_id: int) -> bool:
    """Проверить, состоит ли пользователь в основной группе."""
    try:
        member = await bot.get_chat_member(chat_id=settings.GENERAL_GROUP_ID, user_id=user_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return False

    return member.status not in {"left", "kicked"}


async def create_personal_invite_link(bot: Bot, user_id: int) -> ChatInviteLink:
    """Создать одноразовую ссылку на один час для конкретного пользователя."""
    return await bot.create_chat_invite_link(
        chat_id=settings.GENERAL_GROUP_ID,
        name=f"user_{user_id}",
        member_limit=1,
        expire_date=datetime.now(settings.MOSCOW_TZ) + timedelta(hours=1),
    )
