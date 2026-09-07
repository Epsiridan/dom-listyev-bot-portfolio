# -*- coding: utf-8 -*-
"""Сценарий входа в сообщество: правила → одноразовая invite-ссылка."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from handlers.access import is_admin
from handlers.screens import safe_edit_or_answer, send_content_screen
from keyboards import (
    admin_main_menu_keyboard,
    main_menu_keyboard,
    restart_keyboard,
    rules_keyboard,
)
from services.community import create_personal_invite_link, user_is_member
from services.contest_database import get_visible_contests
from services.content import get_text

router = Router()


def _main_menu_keyboard_for_user(user_id: int, chat_type: str):
    """Выбрать меню по роли пользователя без дублирования в обработчике."""
    if chat_type == "private" and is_admin(user_id):
        return admin_main_menu_keyboard(get_visible_contests())
    return main_menu_keyboard(get_visible_contests())


@router.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Сбросить текущий сценарий и показать короткий главный экран."""
    await state.clear()
    await safe_edit_or_answer(
        callback,
        get_text("main_menu_short"),
        reply_markup=_main_menu_keyboard_for_user(
            callback.from_user.id,
            callback.message.chat.type,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "join_community")
async def join_community(callback: CallbackQuery, bot: Bot) -> None:
    """Показать правила, если пользователь ещё не состоит в группе."""
    if await user_is_member(bot, callback.from_user.id):
        await safe_edit_or_answer(callback, get_text("already_in_community"), reply_markup=restart_keyboard)
    else:
        await send_content_screen(callback, "community_rules", reply_markup=rules_keyboard)
    await callback.answer()


@router.callback_query(F.data == "accept_rules")
async def accept_rules(callback: CallbackQuery, bot: Bot) -> None:
    """После принятия правил выдать персональную ссылку на один вход."""
    if await user_is_member(bot, callback.from_user.id):
        await safe_edit_or_answer(callback, get_text("already_in_community"), reply_markup=restart_keyboard)
        await callback.answer()
        return

    invite = await create_personal_invite_link(bot, callback.from_user.id)

    await send_content_screen(callback, "community_invite", values={"invite_link": invite.invite_link}, reply_markup=restart_keyboard)

    await callback.answer()
