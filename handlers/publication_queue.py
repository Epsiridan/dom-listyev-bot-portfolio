# -*- coding: utf-8 -*-
"""Админский экран очереди публикаций."""

from aiogram import Bot
from aiogram import F, Router
from aiogram.types import CallbackQuery

from handlers.access import require_private_admin_callback
from handlers.screens import safe_edit_or_answer
from keyboards import confirm_queue_delete_keyboard, publication_queue_keyboard
from services.database import (
    delete_approved_proposed_post_and_shift_queue,
    get_approved_proposed_posts,
    get_proposed_post,
)
from services.publications import (
    format_scheduled_for,
    notify_author_about_queue_removal,
    notify_author_about_queue_shift,
)
from services.telegram_utils import callback_int_id

router = Router()
PRIVATE_ADMIN_DENIAL_TEXT = "Очередь публикаций доступна только администраторам в личке с ботом."


async def _require_private_admin(callback: CallbackQuery) -> bool:
    """Проверить доступ и показать alert при отказе."""
    return await require_private_admin_callback(callback, PRIVATE_ADMIN_DENIAL_TEXT)


def _author_line(post) -> str:
    """Короткая строка автора с учётом анонимной публикации."""
    if post["publish_author"]:
        if post["username"]:
            return f"Автор: @{post['username']}"
        if post["full_name"]:
            return f"Автор: {post['full_name']}"
    return "Автор: анонимно"


def _queue_text(posts) -> str:
    """Собрать текст админского списка очереди."""
    if not posts:
        return (
            "🗓 Очередь публикаций\n\n"
            "Сейчас в очереди нет одобренных листов."
        )

    lines = [
        "🗓 Очередь публикаций",
        "",
        "Одобренные листы, ожидающие публикации:",
    ]
    for index, post in enumerate(posts, start=1):
        lines.extend(
            [
                "",
                f"{index}. Лист #{post['id']}",
                f"Дата: {format_scheduled_for(post['scheduled_for'])}",
                _author_line(post),
            ]
        )
        if post["creative_group"]:
            lines.append(f"Группа: {post['creative_group']}")
        if post["admin_message_id"]:
            lines.append("Предложка: кнопка под сообщением")

    return "\n".join(lines)


async def _show_queue(callback: CallbackQuery, *, notice: str | None = None) -> None:
    """Показать/обновить очередь и ответить callback-уведомлением."""
    posts = get_approved_proposed_posts(limit=30)
    text = _queue_text(posts)
    keyboard = publication_queue_keyboard(posts)

    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )

    await callback.answer(notice)


@router.callback_query(F.data == "admin_publication_queue")
async def show_publication_queue(callback: CallbackQuery) -> None:
    """Открыть очередь публикаций из админского меню."""
    if not await _require_private_admin(callback):
        return

    await _show_queue(callback)


@router.callback_query(F.data.startswith("admin_queue_delete:"))
async def confirm_delete_from_queue(callback: CallbackQuery) -> None:
    """Попросить подтверждение перед удалением листа из очереди."""
    if not await _require_private_admin(callback):
        return

    post_id = callback_int_id(callback.data)
    post = get_proposed_post(post_id)
    if post is None or post["status"] != "approved":
        await _show_queue(callback, notice="Лист уже не в очереди.")
        return

    await safe_edit_or_answer(
        callback,
        (
            f"🗑 Удалить лист #{post_id} из очереди публикаций?\n\n"
            "Все следующие листы в очереди сдвинутся на один день раньше, "
            "чтобы закрыть освободившийся слот."
        ),
        reply_markup=confirm_queue_delete_keyboard(post_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_queue_delete_confirm:"))
async def delete_from_queue(callback: CallbackQuery, bot: Bot) -> None:
    """Удалить лист, сдвинуть очередь и уведомить затронутых авторов."""
    if not await _require_private_admin(callback):
        return

    post_id = callback_int_id(callback.data)
    deleted, deleted_post, shifted_posts = delete_approved_proposed_post_and_shift_queue(post_id)
    if deleted:
        removed_author_notified = False
        if deleted_post is not None:
            removed_author_notified = await notify_author_about_queue_removal(
                bot,
                deleted_post,
            )

        notified_count = 0
        for shifted_post in shifted_posts:
            if await notify_author_about_queue_shift(bot, shifted_post):
                notified_count += 1

        notice = f"Лист #{post_id} удалён. Очередь сдвинута."
        if deleted_post is not None or shifted_posts:
            notice += (
                " Уведомления: удалённому автору — "
                f"{'да' if removed_author_notified else 'нет'}, "
                f"сдвинутым — {notified_count}/{len(shifted_posts)}."
            )

        await _show_queue(callback, notice=notice)
    else:
        await _show_queue(callback, notice="Лист уже не в очереди.")
