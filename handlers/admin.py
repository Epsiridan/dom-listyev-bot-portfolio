# -*- coding: utf-8 -*-
"""Админские и диагностические команды.

Команды здесь доступны из лички/групп, но опасные операции обязательно проходят
через `require_admin`, чтобы случайный пользователь не мог чистить базу.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.access import is_admin, require_admin, require_private_admin_callback
from handlers.screens import safe_edit_or_answer
from keyboards import (
    admin_back_keyboard,
    admin_panel_keyboard,
    admin_submission_tools_keyboard,
    cleanup_published_keyboard,
    confirm_clear_submissions_keyboard,
    restart_keyboard,
)
from services.database import (
    cleanup_published_proposed_posts,
    clear_submissions,
    delete_submission,
    delete_submission_by_username,
)
from services.telegram_utils import callback_value
from states import AdminMaintenance

router = Router()
VALID_CLEANUP_DAYS = {30, 60, 90}


async def _require_private_admin(callback: CallbackQuery) -> bool:
    """Проверить доступ к кнопочному админскому разделу в личке."""
    return await require_private_admin_callback(
        callback,
        "Администрация доступна только администраторам в личке с ботом.",
    )


async def _show_callback_screen(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
    """Аккуратно заменить текущий экран или отправить новый, если Telegram отказал."""
    await safe_edit_or_answer(callback, text, reply_markup=reply_markup, parse_mode=parse_mode)


def _delete_submission_by_ref(user_ref: str) -> tuple[int, str]:
    """Удалить заявку по Telegram ID или username и вернуть количество/ярлык."""
    if user_ref.lstrip("-").isdigit():
        deleted = 1 if delete_submission(int(user_ref)) else 0
        return deleted, f"ID {user_ref}"

    username = user_ref.lstrip("@")
    deleted = delete_submission_by_username(username)
    return deleted, f"@{username}"


@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть единый админский раздел из главного меню."""
    if not await _require_private_admin(callback):
        return

    await state.clear()
    await _show_callback_screen(
        callback,
        "🛡 Администрация\n\nВыберите раздел:",
        reply_markup=admin_panel_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_submission_tools")
async def show_submission_tools(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать кнопки обслуживания конкурсных заявок."""
    if not await _require_private_admin(callback):
        return

    await state.clear()
    await _show_callback_screen(
        callback,
        "🧾 Конкурсные заявки\n\nЗдесь собраны админские действия по заявкам.",
        reply_markup=admin_submission_tools_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_reset_my_submission")
async def reset_my_submission_button(callback: CallbackQuery) -> None:
    """Кнопочный вариант `/reset_my_submission`."""
    if not await _require_private_admin(callback):
        return

    deleted = delete_submission(callback.from_user.id)
    text = (
        "Готово. Ваша запись об отправке работы удалена — можно тестировать заново."
        if deleted
        else "У вас не было сохранённой записи об отправке работы."
    )
    await _show_callback_screen(callback, text, reply_markup=admin_submission_tools_keyboard)
    await callback.answer()


@router.callback_query(F.data == "admin_delete_submission")
async def ask_submission_to_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Запросить пользователя для удаления конкурсной заявки."""
    if not await _require_private_admin(callback):
        return

    await state.set_state(AdminMaintenance.waiting_submission_ref)
    await _show_callback_screen(
        callback,
        "🗑 Удаление конкурсной заявки\n\n"
        "Пришлите Telegram ID или username пользователя.\n\n"
        "Примеры:\n"
        "123456789\n"
        "@username",
        reply_markup=admin_back_keyboard,
    )
    await callback.answer()


@router.message(AdminMaintenance.waiting_submission_ref, F.chat.type == "private")
async def delete_submission_ref_received(message: Message, state: FSMContext) -> None:
    """Удалить конкурсную заявку после ввода ID или username."""
    if not message.from_user or not is_admin(message.from_user.id):
        return

    user_ref = (message.text or "").strip()
    if not user_ref:
        await message.answer(
            "Пришлите Telegram ID или username пользователя.",
            reply_markup=admin_back_keyboard,
        )
        return

    deleted, target_label = _delete_submission_by_ref(user_ref)
    await state.clear()
    if deleted:
        await message.answer(
            f"Готово. Удалено заявок для {target_label}: {deleted}.",
            reply_markup=admin_submission_tools_keyboard,
        )
    else:
        await message.answer(
            f"Заявка для {target_label} не найдена.",
            reply_markup=admin_submission_tools_keyboard,
        )


@router.callback_query(F.data == "admin_clear_submissions")
async def confirm_clear_submissions(callback: CallbackQuery) -> None:
    """Попросить подтверждение перед полной очисткой заявок."""
    if not await _require_private_admin(callback):
        return

    await _show_callback_screen(
        callback,
        "⚠️ Очистить все конкурсные заявки?\n\n"
        "Действие необратимо. Используйте только для тестов или обслуживания.",
        reply_markup=confirm_clear_submissions_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_clear_submissions_confirm")
async def clear_submissions_button(callback: CallbackQuery) -> None:
    """Кнопочный вариант `/clear_submissions` с подтверждением."""
    if not await _require_private_admin(callback):
        return

    deleted_count = clear_submissions()
    await _show_callback_screen(
        callback,
        f"Готово. Очищена история отправки работ. Удалено записей: {deleted_count}.",
        reply_markup=admin_submission_tools_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cleanup_tools")
async def show_cleanup_tools(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать кнопки очистки опубликованных листов."""
    if not await _require_private_admin(callback):
        return

    await state.clear()
    await _show_callback_screen(
        callback,
        "🧹 Очистка опубликованных листов\n\n"
        "Выберите срок хранения опубликованных листов:",
        reply_markup=cleanup_published_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cleanup_published:"))
async def cleanup_published_button(callback: CallbackQuery) -> None:
    """Кнопочный вариант `/cleanup_published 30/60/90`."""
    if not await _require_private_admin(callback):
        return

    raw_days = callback_value(callback.data)
    days = int(raw_days) if raw_days.isdigit() else 0
    if days not in VALID_CLEANUP_DAYS:
        await callback.answer("Недоступный срок хранения.", show_alert=True)
        return

    deleted_count = cleanup_published_proposed_posts(days)
    await _show_callback_screen(
        callback,
        f"Готово. Удалены опубликованные посты старше {days} дней: {deleted_count}.",
        reply_markup=cleanup_published_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_diagnostics")
async def show_admin_diagnostics(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать админские подсказки по диагностическим ID."""
    if not await _require_private_admin(callback):
        return

    await state.clear()
    await _show_callback_screen(
        callback,
        "🆔 Диагностика ID\n\n"
        f"Ваш Telegram ID: `{callback.from_user.id}`\n\n"
        "Чтобы узнать ID группы или топика, отправьте в нужной группе/топике:\n"
        "/topic_id\n\n"
        "Также в группе можно написать:\n"
        "@DomListyevBot id",
        reply_markup=admin_back_keyboard,
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(Command("my_id"))
async def my_id(message: Message) -> None:
    """Показать пользователю его Telegram ID для добавления в ADMIN_IDS."""
    if not message.from_user:
        await message.answer("Не удалось определить ваш Telegram ID.", reply_markup=restart_keyboard)
        return

    await message.answer(
        f"Ваш Telegram ID: `{message.from_user.id}`",
        parse_mode="Markdown",
        reply_markup=restart_keyboard,
    )


@router.message(Command("reset_my_submission"))
async def reset_my_submission(message: Message) -> None:
    """Удалить тестовую конкурсную заявку текущего администратора."""
    if not await require_admin(message):
        return

    deleted = delete_submission(message.from_user.id)
    if deleted:
        await message.answer(
            "Готово. Ваша запись об отправке работы удалена — можно тестировать заново.",
            reply_markup=restart_keyboard,
        )
    else:
        await message.answer(
            "У вас не было сохранённой записи об отправке работы.",
            reply_markup=restart_keyboard,
        )


@router.message(Command("delete_submission"))
async def delete_user_submission(message: Message) -> None:
    """Удалить конкурсную заявку по Telegram ID или username."""
    if not await require_admin(message):
        return

    command_parts = (message.text or "").split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        await message.answer(
            "Укажите пользователя после команды.\n\n"
            "Примеры:\n"
            "/delete_submission @username\n"
            "/delete_submission 123456789",
            reply_markup=restart_keyboard,
        )
        return

    deleted, target_label = _delete_submission_by_ref(command_parts[1].strip())

    if deleted:
        await message.answer(
            f"Готово. Удалено заявок для {target_label}: {deleted}.",
            reply_markup=restart_keyboard,
        )
    else:
        await message.answer(
            f"Заявка для {target_label} не найдена.",
            reply_markup=restart_keyboard,
        )


@router.message(Command("clear_submissions"))
async def clear_all_submissions(message: Message) -> None:
    """Полностью очистить историю конкурсных заявок."""
    if not await require_admin(message):
        return

    deleted_count = clear_submissions()
    await message.answer(
        f"Готово. Очищена история отправки работ. Удалено записей: {deleted_count}.",
        reply_markup=restart_keyboard,
    )



@router.message(Command("cleanup_published"))
async def cleanup_published(message: Message) -> None:
    """Удалить опубликованные листы старше безопасного выбранного срока."""
    if not await require_admin(message):
        return

    command_parts = (message.text or "").split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        await message.answer(
            "Укажите срок хранения: 30, 60 или 90 дней.\n\n"
            "Пример: /cleanup_published 90",
            reply_markup=restart_keyboard,
        )
        return

    raw_days = command_parts[1].strip()
    if not raw_days.isdigit():
        await message.answer(
            "Срок должен быть числом: 30, 60 или 90.",
            reply_markup=restart_keyboard,
        )
        return

    days = int(raw_days)
    if days not in VALID_CLEANUP_DAYS:
        await message.answer(
            "Для безопасности доступны только варианты: 30, 60 или 90 дней.\n\n"
            "Пример: /cleanup_published 90",
            reply_markup=restart_keyboard,
        )
        return

    deleted_count = cleanup_published_proposed_posts(days)
    await message.answer(
        f"Готово. Удалены опубликованные посты старше {days} дней: {deleted_count}.",
        reply_markup=restart_keyboard,
    )



async def send_topic_id(message: Message) -> None:
    """Отправить chat_id/thread_id для настройки переменных окружения."""
    await message.answer(
        "chat_id: `{chat_id}`\nmessage_thread_id: `{thread_id}`\nchat_type: `{chat_type}`".format(
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
            chat_type=message.chat.type,
        ),
        parse_mode="Markdown",
        reply_markup=restart_keyboard,
    )


@router.message(Command("topic_id"), F.chat.type.in_({"group", "supergroup"}))
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"^/topic_id(?:@\w+)?$"))
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^@DomListyevBot\s+id$"))
async def topic_id(message: Message) -> None:
    """Диагностика ID топика в группах и супергруппах."""
    await send_topic_id(message)


@router.channel_post(Command("topic_id"))
@router.channel_post(F.text.regexp(r"^/topic_id(?:@\w+)?$"))
@router.channel_post(F.text.regexp(r"(?i)^@DomListyevBot\s+id$"))
async def channel_topic_id(message: Message) -> None:
    """Диагностика ID для channel_post-событий."""
    await send_topic_id(message)
