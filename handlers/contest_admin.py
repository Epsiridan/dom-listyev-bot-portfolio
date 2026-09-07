# -*- coding: utf-8 -*-
"""Админский конструктор конкурсов."""

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from config import settings
from handlers.access import is_admin, require_private_admin_callback
from handlers.screens import safe_edit_or_answer
from keyboards import (
    admin_contest_detail_keyboard,
    admin_contest_list_keyboard,
    confirm_contest_delete_keyboard,
    confirm_contest_finish_keyboard,
    contest_admin_home_keyboard,
    contest_file_categories_keyboard,
    contest_max_submissions_keyboard,
    contest_preview_keyboard,
    contest_submission_mode_keyboard,
    contest_success_choice_keyboard,
    contest_topic_choice_keyboard,
    destination_group_keyboard,
    yes_no_keyboard,
)
from services.contest_database import (
    count_contest_submissions,
    create_contest,
    delete_contest,
    finish_contest,
    get_admin_active_contests,
    get_archived_contests,
    get_contest,
    get_contest_channels,
)
from services.contests import (
    FILE_CATEGORY_LABELS,
    build_admin_contest_text,
    default_success_message,
    format_allowed_categories,
    format_contest_datetime,
    parse_contest_datetime,
    parse_topic_message_link,
    plain_from_html,
    submission_mode_label,
    validate_required_channels,
)
from services.telegram_utils import callback_int_id, callback_value
from states import ContestAdmin

router = Router()
DENIAL_TEXT = "Администрация конкурсов доступна только администраторам в личке с ботом."


async def _require_admin(callback: CallbackQuery) -> bool:
    return await require_private_admin_callback(callback, DENIAL_TEXT)


async def _edit(callback: CallbackQuery, text: str, *, reply_markup=None) -> None:
    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


def _valid_private_admin_message(message: Message) -> bool:
    return bool(
        message.from_user
        and message.chat.type == "private"
        and is_admin(message.from_user.id)
    )


def _validate_plain_text(message: Message, *, field: str, max_len: int) -> str | None:
    plain = (message.text or "").strip()
    if not plain:
        return f"{field} нужно отправить обычным текстовым сообщением."
    if len(plain) > max_len:
        return f"{field} слишком длинное. Максимум: {max_len} символов."
    return None


def _html_text(message: Message) -> str:
    return (getattr(message, "html_text", None) or message.text or "").strip()


def _rich_text_too_long(message: Message, *, max_len: int = 3500) -> bool:
    """HTML-теги тоже входят в лимит Telegram-сообщения."""
    return len(_html_text(message)) > max_len


def _draft_preview(data: dict) -> str:
    channels = data.get("required_channels", [])
    channel_text = ", ".join(item["title"] for item in channels) or "не проверяются"
    limit = data.get("max_submissions")
    limit_text = str(limit) if limit is not None else "без ограничения"
    destination = data.get("destination_chat_title") or str(data.get("destination_chat_id"))
    if data.get("destination_thread_id") is not None:
        destination += f", топик {data['destination_thread_id']}"
    description = plain_from_html(data.get("description_html", ""))
    if len(description) > 500:
        description = description[:499].rstrip() + "…"
    return (
        "👀 Проверьте конкурс перед публикацией.\n\n"
        f"Кнопка: {data['button_text']}\n"
        f"Начало: {format_contest_datetime(data['starts_at'])}\n"
        f"Окончание: {format_contest_datetime(data['ends_at'])}\n"
        f"Правила сообщества: {'показывать' if data['show_community_rules'] else 'не показывать'}\n"
        f"Репост: {'нужен' if data['require_repost'] else 'не нужен'}\n"
        f"Вопрос про ИИ: {'да' if data['ask_ai'] else 'нет'}\n"
        f"Формат: {submission_mode_label(data['submission_mode'])}\n"
        f"Типы файлов: {format_allowed_categories(data.get('allowed_file_categories', []))}\n"
        f"Лимит: {limit_text}\n"
        f"Каналы: {channel_text}\n"
        f"Куда складывать: {destination}\n\n"
        f"Фрагмент текста:\n{description}"
    )


async def _show_home(callback: CallbackQuery, *, notice: str | None = None) -> None:
    await _edit(
        callback,
        "🎨 Администрация конкурсов\n\nВыберите действие:",
        reply_markup=contest_admin_home_keyboard,
    )
    await callback.answer(notice)


async def _show_detail(callback: CallbackQuery, contest_id: int, *, notice: str | None = None) -> None:
    contest = get_contest(contest_id)
    if contest is None:
        await _show_home(callback, notice="Конкурс не найден.")
        return
    active = contest["status"] == "active" and datetime.fromisoformat(contest["ends_at"]) >= datetime.now(settings.MOSCOW_TZ)
    await _edit(
        callback,
        build_admin_contest_text(
            contest,
            submissions_count=count_contest_submissions(contest_id),
            channels=get_contest_channels(contest_id),
        ),
        reply_markup=admin_contest_detail_keyboard(contest_id, active=active),
    )
    await callback.answer(notice)


async def _ask_ai(callback: CallbackQuery) -> None:
    await _edit(
        callback,
        "Спрашивать участника, использовался ли ИИ при создании работы?",
        reply_markup=yes_no_keyboard("admin_contest_ai"),
    )


async def _ask_destination_message(message: Message, state: FSMContext) -> None:
    await state.set_state(ContestAdmin.waiting_destination_chat)
    await message.answer(
        "🏠 Выберите группу, куда бот будет складывать конкурсные работы.\n\n"
        "Telegram покажет группы, где бот уже состоит. У бота должно быть право отправлять сообщения.",
        reply_markup=destination_group_keyboard(),
    )


async def _ask_destination_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ContestAdmin.waiting_destination_chat)
    await _edit(callback, "Теперь выберите группу кнопкой в новом сообщении.")
    await callback.message.answer(
        "🏠 Куда складывать работы?",
        reply_markup=destination_group_keyboard(),
    )


async def _preview_from_message(message: Message, state: FSMContext) -> None:
    await state.set_state(ContestAdmin.reviewing)
    await message.answer(_draft_preview(await state.get_data()), reply_markup=contest_preview_keyboard)


async def _preview_from_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ContestAdmin.reviewing)
    await _edit(callback, _draft_preview(await state.get_data()), reply_markup=contest_preview_keyboard)


@router.callback_query(F.data == "admin_contests")
async def show_admin_contests(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.clear()
    await _show_home(callback)


@router.callback_query(F.data == "admin_contest_active")
async def show_active(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    contests = get_admin_active_contests()
    text = "📋 Активные конкурсы\n\nВыберите конкурс:" if contests else "📋 Активных конкурсов нет."
    await _edit(callback, text, reply_markup=admin_contest_list_keyboard(contests))
    await callback.answer()


@router.callback_query(F.data == "admin_contest_archive")
async def show_archive(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    contests = get_archived_contests()
    text = "🕰 Архив конкурсов\n\nВыберите конкурс:" if contests else "🕰 Архив конкурсов пуст."
    await _edit(callback, text, reply_markup=admin_contest_list_keyboard(contests, archive=True))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_view:"))
async def show_detail(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    await _show_detail(callback, callback_int_id(callback.data))


@router.callback_query(F.data.startswith("admin_contest_archive_view:"))
async def show_archive_detail(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    await _show_detail(callback, callback_int_id(callback.data))


@router.callback_query(F.data.startswith("admin_contest_finish:"))
async def confirm_finish(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    contest_id = callback_int_id(callback.data)
    await _edit(
        callback,
        "⏹ Закончить конкурс досрочно?\n\nПриём работ сразу закроется, а кнопка конкурса исчезнет из нового главного меню.",
        reply_markup=confirm_contest_finish_keyboard(contest_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_finish_confirm:"))
async def finish_confirmed(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    ok = finish_contest(callback_int_id(callback.data))
    await _show_home(callback, notice="Конкурс завершён." if ok else "Не удалось завершить конкурс.")


@router.callback_query(F.data.startswith("admin_contest_delete:"))
async def confirm_delete(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    contest_id = callback_int_id(callback.data)
    contest = get_contest(contest_id)
    if contest is None:
        await _show_home(callback, notice="Конкурс не найден.")
        return
    archived = (
        contest["status"] != "active"
        or datetime.fromisoformat(contest["ends_at"]) < datetime.now(settings.MOSCOW_TZ)
    )
    await _edit(
        callback,
        "🗑 Удалить конкурс навсегда?\n\n"
        "Будут удалены конкурс, список проверяемых каналов и все конкурсные заявки. "
        "Кнопка исчезнет из нового главного меню. Отменить это действие нельзя.",
        reply_markup=confirm_contest_delete_keyboard(contest_id, archived=archived),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_delete_confirm:"))
async def delete_confirmed(callback: CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    ok = delete_contest(callback_int_id(callback.data))
    await _show_home(
        callback,
        notice="Конкурс и все связанные данные удалены." if ok else "Конкурс уже удалён.",
    )


@router.callback_query(F.data == "admin_contest_create")
async def start_creation(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.clear()
    await state.set_state(ContestAdmin.waiting_title)
    await _edit(callback, "➕ Создаём конкурс.\n\nНапишите название. Оно же появится на кнопке главного меню.")
    await callback.answer()


@router.message(ContestAdmin.waiting_title, F.chat.type == "private")
async def title_received(message: Message, state: FSMContext) -> None:
    if not _valid_private_admin_message(message):
        return
    error = _validate_plain_text(message, field="Название", max_len=52)
    if error:
        await message.answer(error)
        return
    title = message.text.strip()
    await state.update_data(title=title, button_text=f"🎨 {title}")
    await message.answer(
        "Показывать в карточке конкурса кнопку «📖 Правила сообщества»?",
        reply_markup=yes_no_keyboard("admin_contest_rules"),
    )


@router.callback_query(F.data.startswith("admin_contest_rules:"))
async def rules_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(show_community_rules=callback_value(callback.data) == "yes")
    await state.set_state(ContestAdmin.waiting_description)
    await _edit(
        callback,
        "Отправьте текст конкурса одним сообщением.\n\n"
        "Можно использовать Telegram-форматирование: жирный, курсив, ссылки, скрытый текст и другие стандартные стили.",
    )
    await callback.answer()


@router.message(ContestAdmin.waiting_description, F.chat.type == "private")
async def description_received(message: Message, state: FSMContext) -> None:
    if not _valid_private_admin_message(message):
        return
    error = _validate_plain_text(message, field="Текст конкурса", max_len=3500)
    if error:
        await message.answer(error)
        return
    if _rich_text_too_long(message):
        await message.answer("Из-за форматирования текст превышает безопасный лимит Telegram. Немного сократите его.")
        return
    await state.update_data(description_html=_html_text(message))
    await state.set_state(ContestAdmin.waiting_start)
    await message.answer("Укажите начало приёма работ по Москве.\n\nФормат: 20.08.2026 18:00")


@router.message(ContestAdmin.waiting_start, F.chat.type == "private")
async def start_received(message: Message, state: FSMContext) -> None:
    if not _valid_private_admin_message(message):
        return
    try:
        starts_at = parse_contest_datetime(message.text or "")
    except ValueError:
        await message.answer("Не смог разобрать дату. Напишите так: 20.08.2026 18:00")
        return
    await state.update_data(starts_at=starts_at.isoformat(timespec="seconds"))
    await state.set_state(ContestAdmin.waiting_end)
    await message.answer("Укажите окончание приёма работ по Москве.\n\nФормат: 31.08.2026 21:00")


@router.message(ContestAdmin.waiting_end, F.chat.type == "private")
async def end_received(message: Message, state: FSMContext) -> None:
    if not _valid_private_admin_message(message):
        return
    try:
        ends_at = parse_contest_datetime(message.text or "")
    except ValueError:
        await message.answer("Не смог разобрать дату. Напишите так: 31.08.2026 21:00")
        return
    data = await state.get_data()
    starts_at = datetime.fromisoformat(data["starts_at"])
    if ends_at <= starts_at:
        await message.answer("Окончание должно быть позже начала. Повторите дату окончания.")
        return
    if ends_at <= datetime.now(settings.MOSCOW_TZ):
        await message.answer("Окончание уже прошло. Укажите будущее время.")
        return
    await state.update_data(ends_at=ends_at.isoformat(timespec="seconds"))
    await state.set_state(ContestAdmin.waiting_criteria)
    await message.answer(
        "Отправьте критерии оценивания одним сообщением.\n\nTelegram-форматирование сохранится."
    )


@router.message(ContestAdmin.waiting_criteria, F.chat.type == "private")
async def criteria_received(message: Message, state: FSMContext) -> None:
    if not _valid_private_admin_message(message):
        return
    error = _validate_plain_text(message, field="Критерии", max_len=3500)
    if error:
        await message.answer(error)
        return
    if _rich_text_too_long(message):
        await message.answer("Из-за форматирования критерии превышают безопасный лимит Telegram. Немного сократите их.")
        return
    await state.update_data(criteria_html=_html_text(message))
    await message.answer(
        "Требовать от участника ссылку на репост анонса конкурса?",
        reply_markup=yes_no_keyboard("admin_contest_repost"),
    )


@router.callback_query(F.data.startswith("admin_contest_repost:"))
async def repost_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(require_repost=callback_value(callback.data) == "yes")
    await _edit(
        callback,
        "Проверять ли подписку участников на Telegram-каналы?",
        reply_markup=yes_no_keyboard("admin_contest_subscriptions"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_subscriptions:"))
async def subscriptions_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if callback_value(callback.data) == "no":
        await state.update_data(required_channels=[])
        await _ask_ai(callback)
        await callback.answer()
        return
    await state.set_state(ContestAdmin.waiting_channels)
    await _edit(
        callback,
        "Пришлите полный список каналов одним сообщением. Ссылки можно разделять пробелами или новыми строками.\n\n"
        "Пример:\nhttps://t.me/channel_one https://t.me/channel_two\n\n"
        "⚠️ Бот должен быть администратором каждого канала. Для закрытых каналов invite-ссылки t.me/+... недостаточно: нужен публичный @username.",
    )
    await callback.answer()


@router.message(ContestAdmin.waiting_channels, F.chat.type == "private")
async def channels_received(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _valid_private_admin_message(message):
        return
    channels, errors = await validate_required_channels(bot, message.text or "")
    if errors:
        lines = "\n".join(f"• {error}" for error in errors)
        await message.answer(
            "Вот на каких каналах меня нет или я не могу проверить подписку:\n\n"
            f"{lines}\n\n"
            "Добавьте бота в администраторы и повторите попытку. Пришлите снова весь полный список каналов."
        )
        return
    await state.update_data(required_channels=channels)
    await message.answer("✅ Бот найден администратором во всех указанных каналах.")
    await message.answer(
        "Спрашивать участника, использовался ли ИИ при создании работы?",
        reply_markup=yes_no_keyboard("admin_contest_ai"),
    )


@router.callback_query(F.data.startswith("admin_contest_ai:"))
async def ai_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(ask_ai=callback_value(callback.data) == "yes")
    await _edit(callback, "В каком виде принимать работы?", reply_markup=contest_submission_mode_keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_mode:"))
async def mode_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    mode = callback_value(callback.data)
    await state.update_data(submission_mode=mode)
    if mode == "text":
        await state.update_data(allowed_file_categories=[])
        await _edit(callback, "Сколько работ может отправить один участник?", reply_markup=contest_max_submissions_keyboard)
    else:
        await state.update_data(allowed_file_categories=[])
        await state.set_state(ContestAdmin.choosing_files)
        await _edit(
            callback,
            "Выберите допустимые типы файлов. Можно отметить несколько вариантов, затем нажать «Далее».",
            reply_markup=contest_file_categories_keyboard([]),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_file:"))
async def file_category_toggled(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    key = callback_value(callback.data)
    if key not in FILE_CATEGORY_LABELS:
        await callback.answer("Неизвестный тип файла.", show_alert=True)
        return
    data = await state.get_data()
    selected = list(data.get("allowed_file_categories", []))
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(allowed_file_categories=selected)
    await _edit(callback, "Выберите допустимые типы файлов:", reply_markup=contest_file_categories_keyboard(selected))
    await callback.answer()


@router.callback_query(F.data == "admin_contest_file_done")
async def file_categories_done(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await state.get_data()
    if not data.get("allowed_file_categories"):
        await callback.answer("Отметьте хотя бы один тип файлов.", show_alert=True)
        return
    await _edit(callback, "Сколько работ может отправить один участник?", reply_markup=contest_max_submissions_keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_max:"))
async def max_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    raw = callback_value(callback.data)
    await state.update_data(max_submissions=None if raw == "none" else int(raw))
    await _edit(
        callback,
        "Какое сообщение показать участнику после успешной отправки работы?",
        reply_markup=contest_success_choice_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contest_success:"))
async def success_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if callback_value(callback.data) == "default":
        data = await state.get_data()
        await state.update_data(success_message_html=default_success_message(data["title"]))
        await _ask_destination_callback(callback, state)
    else:
        await state.set_state(ContestAdmin.waiting_success_message)
        await _edit(
            callback,
            "Отправьте своё сообщение участнику после успешной отправки.\n\nTelegram-форматирование сохранится.",
        )
    await callback.answer()


@router.message(ContestAdmin.waiting_success_message, F.chat.type == "private")
async def success_message_received(message: Message, state: FSMContext) -> None:
    if not _valid_private_admin_message(message):
        return
    error = _validate_plain_text(message, field="Сообщение", max_len=3500)
    if error:
        await message.answer(error)
        return
    if _rich_text_too_long(message):
        await message.answer("Из-за форматирования сообщение превышает безопасный лимит Telegram. Немного сократите его.")
        return
    await state.update_data(success_message_html=_html_text(message))
    await _ask_destination_message(message, state)


@router.message(ContestAdmin.waiting_destination_chat, F.chat_shared)
async def destination_chat_received(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _valid_private_admin_message(message) or message.chat_shared is None:
        return
    chat_id = message.chat_shared.chat_id
    try:
        chat = await bot.get_chat(chat_id)
        bot_user = await bot.get_me()
        member = await bot.get_chat_member(chat_id, bot_user.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer("Не могу открыть эту группу. Добавьте туда бота и повторите выбор.", reply_markup=destination_group_keyboard())
        return
    if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        await message.answer("Бота нет в этой группе. Добавьте его и повторите выбор.", reply_markup=destination_group_keyboard())
        return
    if member.status == ChatMemberStatus.RESTRICTED and not getattr(member, "can_send_messages", False):
        await message.answer("Бот состоит в этой группе, но не может отправлять сообщения. Выдайте ему право на отправку и повторите выбор.", reply_markup=destination_group_keyboard())
        return
    await state.update_data(
        destination_chat_id=chat_id,
        destination_chat_title=chat.title or message.chat_shared.title or str(chat_id),
        destination_chat_username=chat.username,
        destination_is_forum=bool(chat.is_forum),
        destination_thread_id=None,
    )
    await message.answer("✅ Группа выбрана.", reply_markup=ReplyKeyboardRemove())
    if chat.is_forum:
        await message.answer(
            "Группа разделена на топики. Куда складывать работы?",
            reply_markup=contest_topic_choice_keyboard,
        )
    else:
        await _preview_from_message(message, state)


@router.message(ContestAdmin.waiting_destination_chat, F.chat.type == "private")
async def destination_chat_expected(message: Message) -> None:
    if _valid_private_admin_message(message):
        await message.answer("Нажмите кнопку «🏠 Выбрать группу» на клавиатуре ниже.", reply_markup=destination_group_keyboard())


@router.callback_query(F.data.startswith("admin_contest_topic:"))
async def topic_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if callback_value(callback.data) == "none":
        await state.update_data(destination_thread_id=None)
        await _preview_from_callback(callback, state)
    else:
        await state.set_state(ContestAdmin.waiting_topic_link)
        await _edit(
            callback,
            "Откройте нужный топик, скопируйте ссылку на любое сообщение в нём и пришлите ссылку сюда.\n\nВводить ID вручную не нужно.",
        )
    await callback.answer()


@router.message(ContestAdmin.waiting_topic_link, F.chat.type == "private")
async def topic_link_received(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _valid_private_admin_message(message):
        return
    data = await state.get_data()
    try:
        topic_id = parse_topic_message_link(
            message.text or "",
            destination_chat_id=int(data["destination_chat_id"]),
            destination_username=data.get("destination_chat_username"),
        )
        await bot.send_chat_action(
            chat_id=int(data["destination_chat_id"]),
            action=ChatAction.TYPING,
            message_thread_id=topic_id,
        )
    except (ValueError, TelegramBadRequest, TelegramForbiddenError) as error:
        await message.answer(f"Не удалось привязать топик: {error}\n\nПришлите ссылку на сообщение из нужного топика ещё раз.")
        return
    await state.update_data(destination_thread_id=topic_id)
    await _preview_from_message(message, state)


@router.callback_query(F.data == "admin_contest_publish")
async def publish_contest(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if await state.get_state() != ContestAdmin.reviewing.state:
        await callback.answer("Черновик конкурса уже сброшен.", show_alert=True)
        return
    data = await state.get_data()
    data["created_by"] = callback.from_user.id
    contest_id = create_contest(data)
    await state.clear()
    await _show_detail(callback, contest_id, notice="Конкурс опубликован.")
