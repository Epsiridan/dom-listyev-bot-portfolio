# -*- coding: utf-8 -*-
"""Проверки доступа для пользовательских и админских обработчиков."""

from aiogram.types import CallbackQuery, Message

from config import settings
from keyboards import restart_keyboard


def is_admin(user_id: int) -> bool:
    """Проверить, входит ли Telegram ID в список администраторов."""
    return user_id in settings.ADMIN_IDS


async def require_admin(message: Message) -> bool:
    """Единая защита текстовых админских команд с понятным ответом."""
    user_id = message.from_user.id if message.from_user else 0
    if is_admin(user_id):
        return True

    await message.answer("Эта команда доступна только администратору.", reply_markup=restart_keyboard)
    return False


def is_private_admin_callback(callback: CallbackQuery) -> bool:
    """True, если callback пришёл от администратора в личке с ботом."""
    return (
        callback.message is not None
        and callback.message.chat.type == "private"
        and is_admin(callback.from_user.id)
    )


async def require_private_admin_callback(
    callback: CallbackQuery,
    denial_text: str = "Админский раздел доступен только администраторам в личке с ботом.",
) -> bool:
    """Единая защита кнопочных админских экранов."""
    if is_private_admin_callback(callback):
        return True

    await callback.answer(denial_text, show_alert=True)
    return False
