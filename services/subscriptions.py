# -*- coding: utf-8 -*-
"""Проверки подписок пользователя на обязательные каналы."""

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


async def is_user_subscribed_to_channel(
    bot: Bot,
    *,
    channel_id: int,
    user_id: int,
) -> bool:
    """Return True when Telegram confirms that the user is a channel member."""
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return False

    if member.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }:
        return True

    if member.status == ChatMemberStatus.RESTRICTED:
        return bool(getattr(member, "is_member", False))

    return False
