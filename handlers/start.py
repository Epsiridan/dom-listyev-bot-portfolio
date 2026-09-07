# -*- coding: utf-8 -*-
"""Стартовые приватные команды: /start и /cancel."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from handlers.access import is_admin
from keyboards import admin_main_menu_keyboard, main_menu_keyboard
from services.contest_database import get_visible_contests
from services.content import send_content

router = Router()


async def send_main_menu(message: Message) -> None:
    """Показать главный экран с админскими пунктами только администраторам."""
    contests = get_visible_contests()
    keyboard = main_menu_keyboard(contests)
    if message.from_user and is_admin(message.from_user.id):
        keyboard = admin_main_menu_keyboard(contests)
    await send_content(message, "main_menu", reply_markup=keyboard)


@router.message(CommandStart(), F.chat.type == "private")
async def start(message: Message, state: FSMContext) -> None:
    """Начать сценарий заново и сбросить возможный незавершённый FSM-диалог."""
    await state.clear()
    await send_main_menu(message)


@router.message(Command("cancel"), F.chat.type == "private")
async def cancel(message: Message, state: FSMContext) -> None:
    """Отменить текущий сценарий и вернуть пользователя в главное меню."""
    await state.clear()
    await message.answer("Действие отменено. Возвращаю в главное меню.", reply_markup=ReplyKeyboardRemove())
    await send_main_menu(message)
