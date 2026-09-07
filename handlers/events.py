# -*- coding: utf-8 -*-
"""Пользовательские и админские сценарии мероприятий Дома Листьев."""

from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import settings
from handlers.access import is_admin, require_private_admin_callback
from handlers.screens import safe_edit_or_answer
from keyboards_parts.editing import edit_confirm_keyboard, edit_prompt_keyboard
from keyboards import (
    confirm_event_cancel_keyboard,
    confirm_event_delete_keyboard,
    event_admin_archive_detail_keyboard,
    event_admin_back_to_detail_keyboard,
    event_admin_detail_keyboard,
    event_admin_events_keyboard,
    event_admin_home_keyboard,
    event_link_choice_keyboard,
    event_extra_reminder_keyboard,
    house_event_detail_keyboard,
    house_events_keyboard,
    restart_keyboard,
)
from services.database import (
    cancel_house_event,
    count_house_event_registrations,
    create_house_event,
    delete_house_event,
    get_active_house_events,
    get_archived_house_events,
    get_house_event,
    get_house_event_registrations,
    register_for_house_event,
    unregister_from_house_event,
    update_house_event_broadcast_text,
    update_house_event_link,
    user_is_registered_for_house_event,
)
from services.events import (
    broadcast_house_event,
    build_event_admin_text,
    build_event_public_text,
    event_registration_is_open,
    format_event_datetime,
    parse_moscow_date,
    parse_moscow_time,
    render_event_broadcast_text,
    send_link_after_late_registration,
    should_send_link_after_registration,
    user_label,
)
from services.telegram_utils import callback_int_id, callback_value
from states import HouseEventAdmin

router = Router()
PRIVATE_ADMIN_DENIAL_TEXT = "Администрация мероприятий доступна только администраторам в личке с ботом."


def _edit_preview(value: str | None, limit: int = 1600) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + "\n…"


# --- Общие помощники и экраны списка/деталей -------------------------------

def _now() -> datetime:
    """Текущее московское время."""
    return datetime.now(settings.MOSCOW_TZ)


async def _require_private_admin(callback: CallbackQuery) -> bool:
    """Проверить права на админский экран мероприятий."""
    return await require_private_admin_callback(callback, PRIVATE_ADMIN_DENIAL_TEXT)


async def _safe_edit_or_answer(callback: CallbackQuery, text: str, *, reply_markup=None) -> None:
    """Обновить текущее callback-сообщение, не создавая новое."""
    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def _show_user_events(callback: CallbackQuery, *, notice: str | None = None) -> None:
    """Показать список активных мероприятий пользователю."""
    events = get_active_house_events()
    if events:
        text = "📅 Мероприятия Дома Листьев\n\nВыберите встречу:"
    else:
        text = "📅 Мероприятия Дома Листьев\n\nПока нет запланированных встреч."
    await _safe_edit_or_answer(
        callback,
        text,
        reply_markup=house_events_keyboard(events),
    )
    await callback.answer(notice)


async def _show_user_event_detail(callback: CallbackQuery, event_id: int, *, notice: str | None = None) -> None:
    """Показать карточку мероприятия пользователю."""
    event = get_house_event(event_id)
    if event is None or not event_registration_is_open(event):
        await _show_user_events(callback, notice="Мероприятие не найдено, отменено или уже в архиве.")
        return

    registered_count = count_house_event_registrations(event_id)
    registered = user_is_registered_for_house_event(event_id, callback.from_user.id)
    await _safe_edit_or_answer(
        callback,
        build_event_public_text(event, registered_count=registered_count),
        reply_markup=house_event_detail_keyboard(event_id, is_registered=registered),
    )
    await callback.answer(notice)


async def _show_admin_home(callback: CallbackQuery, *, notice: str | None = None) -> None:
    """Показать главный экран администрирования мероприятий."""
    await _safe_edit_or_answer(
        callback,
        "🛠 Администрация мероприятий\n\nВыберите действие:",
        reply_markup=event_admin_home_keyboard,
    )
    await callback.answer(notice)


async def _show_admin_event_detail(callback: CallbackQuery, event_id: int, *, notice: str | None = None) -> None:
    """Показать админскую карточку мероприятия."""
    event = get_house_event(event_id)
    if event is None:
        await _show_admin_home(callback, notice="Мероприятие не найдено.")
        return

    registered_count = count_house_event_registrations(event_id)
    await _safe_edit_or_answer(
        callback,
        build_event_admin_text(event, registered_count=registered_count),
        reply_markup=event_admin_detail_keyboard(event_id),
    )
    await callback.answer(notice)


async def _send_admin_event_detail(message: Message, event_id: int) -> None:
    """Отправить админскую карточку после текстового ввода."""
    event = get_house_event(event_id)
    if event is None:
        await message.answer("Мероприятие не найдено.", reply_markup=event_admin_home_keyboard)
        return
    await message.answer(
        build_event_admin_text(
            event,
            registered_count=count_house_event_registrations(event_id),
        ),
        reply_markup=event_admin_detail_keyboard(event_id),
        disable_web_page_preview=True,
    )


def _event_id_from_callback(callback: CallbackQuery) -> int:
    """Достать ID из callback_data вида `prefix:123`."""
    return callback_int_id(callback.data)


def _validate_text(value: str | None, *, max_len: int, field_name: str) -> str | None:
    """Проверить обязательный текстовый ввод."""
    text = (value or "").strip()
    if not text:
        return f"{field_name} не может быть пустым. Попробуйте ещё раз."
    if len(text) > max_len:
        return f"{field_name} слишком длинное. Максимум: {max_len} символов."
    return None


async def _finish_event_creation(message: Message, state: FSMContext, *, link: str | None) -> None:
    """Создать мероприятие из FSM-данных и показать его администратору."""
    data = await state.get_data()
    event_id = create_house_event(
        title=data["title"],
        description=data["description"],
        event_at=data["event_at"],
        reminder_at=data.get("reminder_at"),
        remind_15_min=data.get("remind_15_min", False),
        broadcast_text=data["broadcast_text"],
        link=link,
        created_by=message.from_user.id,
    )
    await state.clear()
    await message.answer("✅ Мероприятие создано.")
    await _send_admin_event_detail(message, event_id)


async def _finish_event_creation_from_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    link: str | None,
) -> None:
    """Создать мероприятие из callback-шага без подмены Telegram Message."""
    data = await state.get_data()
    event_id = create_house_event(
        title=data["title"],
        description=data["description"],
        event_at=data["event_at"],
        reminder_at=data.get("reminder_at"),
        remind_15_min=data.get("remind_15_min", False),
        broadcast_text=data["broadcast_text"],
        link=link,
        created_by=callback.from_user.id,
    )
    await state.clear()
    event = get_house_event(event_id)
    if event is None:
        await _safe_edit_or_answer(
            callback,
            "Мероприятие создано, но не удалось открыть карточку.",
            reply_markup=event_admin_home_keyboard,
        )
        return
    await _safe_edit_or_answer(
        callback,
        "✅ Мероприятие создано.\n\n"
        + build_event_admin_text(
            event,
            registered_count=count_house_event_registrations(event_id),
        ),
        reply_markup=event_admin_detail_keyboard(event_id),
    )


# --- Пользовательская часть: просмотр и запись на мероприятия --------------

@router.callback_query(F.data == "house_events")
async def show_house_events(callback: CallbackQuery) -> None:
    """Открыть пользовательский список мероприятий."""
    await _show_user_events(callback)


@router.callback_query(F.data.startswith("house_event_view:"))
async def show_house_event(callback: CallbackQuery) -> None:
    """Открыть одно мероприятие пользователю."""
    await _show_user_event_detail(callback, _event_id_from_callback(callback))


@router.callback_query(F.data.startswith("house_event_register:"))
async def register_house_event(callback: CallbackQuery) -> None:
    """Записать пользователя на мероприятие."""
    event_id = _event_id_from_callback(callback)
    ok = register_for_house_event(
        event_id=event_id,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    notice = "Вы записаны на мероприятие." if ok else "Не получилось записаться: мероприятие недоступно."
    event = get_house_event(event_id) if ok else None
    if event is not None and should_send_link_after_registration(event):
        try:
            await send_link_after_late_registration(
                callback.bot,
                event,
                callback.from_user.id,
            )
            notice = "Вы записаны. Ссылка на встречу отправлена отдельным сообщением."
        except Exception as error:
            print(
                "late event link failed: "
                f"event_id={event_id} user_id={callback.from_user.id} error={error!r}"
            )
    await _show_user_event_detail(callback, event_id, notice=notice)


@router.callback_query(F.data.startswith("house_event_unregister:"))
async def unregister_house_event(callback: CallbackQuery) -> None:
    """Отменить запись пользователя на мероприятие."""
    event_id = _event_id_from_callback(callback)
    ok = unregister_from_house_event(event_id, callback.from_user.id)
    notice = "Запись отменена." if ok else "Активная запись не найдена."
    await _show_user_event_detail(callback, event_id, notice=notice)


# --- Админская часть: создание, редактирование и рассылка ------------------

@router.callback_query(F.data == "admin_house_events")
async def show_admin_house_events(callback: CallbackQuery) -> None:
    """Открыть администрирование мероприятий из главного меню."""
    if not await _require_private_admin(callback):
        return
    await _show_admin_home(callback)


@router.callback_query(F.data == "admin_event_active")
async def show_admin_active_events(callback: CallbackQuery) -> None:
    """Показать активные мероприятия администратору."""
    if not await _require_private_admin(callback):
        return

    events = get_active_house_events()
    text = "📋 Активные мероприятия\n\nВыберите встречу:" if events else "📋 Активные мероприятия\n\nАктивных мероприятий нет."
    await _safe_edit_or_answer(
        callback,
        text,
        reply_markup=event_admin_events_keyboard(events),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_event_archive")
async def show_admin_archive_events(callback: CallbackQuery) -> None:
    """Показать архив мероприятий администратору."""
    if not await _require_private_admin(callback):
        return

    events = get_archived_house_events()
    text = "🕰 Архив мероприятий\n\nПоследние встречи:" if events else "🕰 Архив мероприятий\n\nАрхив пуст."
    await _safe_edit_or_answer(
        callback,
        text,
        reply_markup=event_admin_events_keyboard(events, archive=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_view:"))
async def show_admin_event(callback: CallbackQuery) -> None:
    """Открыть админскую карточку мероприятия."""
    if not await _require_private_admin(callback):
        return
    await _show_admin_event_detail(callback, _event_id_from_callback(callback))


@router.callback_query(F.data.startswith("admin_event_archive_view:"))
async def show_admin_archived_event(callback: CallbackQuery) -> None:
    """Открыть архивную карточку мероприятия без управляющих действий."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    event = get_house_event(event_id)
    if event is None:
        await _show_admin_home(callback, notice="Мероприятие не найдено.")
        return

    registered_count = count_house_event_registrations(event_id)
    await _safe_edit_or_answer(
        callback,
        "🕰 Архив мероприятий\n\n"
        "Карточка доступна только для просмотра.\n\n"
        + build_event_admin_text(event, registered_count=registered_count),
        reply_markup=event_admin_archive_detail_keyboard(event_id),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_event_create")
async def start_event_creation(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать создание мероприятия."""
    if not await _require_private_admin(callback):
        return

    await state.clear()
    await state.set_state(HouseEventAdmin.waiting_title)
    await _safe_edit_or_answer(callback, "➕ Создаём мероприятие.\n\nНапишите название встречи.")
    await callback.answer()


@router.message(HouseEventAdmin.waiting_title, F.chat.type == "private")
async def event_title_received(message: Message, state: FSMContext) -> None:
    """Принять название мероприятия."""
    if not is_admin(message.from_user.id):
        return
    error = _validate_text(message.text, max_len=120, field_name="Название")
    if error:
        await message.answer(error)
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(HouseEventAdmin.waiting_description)
    await message.answer("Теперь отправьте описание встречи.")


@router.message(HouseEventAdmin.waiting_description, F.chat.type == "private")
async def event_description_received(message: Message, state: FSMContext) -> None:
    """Принять описание мероприятия."""
    if not is_admin(message.from_user.id):
        return
    error = _validate_text(message.text, max_len=2000, field_name="Описание")
    if error:
        await message.answer(error)
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(HouseEventAdmin.waiting_date)
    await message.answer("Укажите дату встречи в формате ДД.ММ.ГГГГ, например: 15.07.2026")


@router.message(HouseEventAdmin.waiting_date, F.chat.type == "private")
async def event_date_received(message: Message, state: FSMContext) -> None:
    """Принять дату мероприятия."""
    if not is_admin(message.from_user.id):
        return
    try:
        parsed_date = parse_moscow_date(message.text or "")
    except ValueError:
        await message.answer("Не смог разобрать дату. Напишите в формате ДД.ММ.ГГГГ, например: 15.07.2026")
        return
    await state.update_data(event_date=parsed_date.date().isoformat())
    await state.set_state(HouseEventAdmin.waiting_time)
    await message.answer("Укажите время по Москве в формате ЧЧ:ММ, например: 18:00")


@router.message(HouseEventAdmin.waiting_time, F.chat.type == "private")
async def event_time_received(message: Message, state: FSMContext) -> None:
    """Принять время мероприятия."""
    if not is_admin(message.from_user.id):
        return
    try:
        hour, minute = parse_moscow_time(message.text or "")
    except ValueError:
        await message.answer("Не смог разобрать время. Напишите в формате ЧЧ:ММ, например: 18:00")
        return

    data = await state.get_data()
    event_date = datetime.fromisoformat(data["event_date"]).replace(tzinfo=settings.MOSCOW_TZ)
    event_at = event_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if event_at <= _now():
        await message.answer("Дата и время встречи уже прошли. Укажите будущую дату/время.")
        await state.set_state(HouseEventAdmin.waiting_date)
        await message.answer("Сначала снова укажите дату в формате ДД.ММ.ГГГГ.")
        return

    await state.update_data(event_at=event_at.isoformat(timespec="seconds"))
    await state.set_state(HouseEventAdmin.waiting_broadcast_text)
    await message.answer(
        "Напишите текст рассылки для записавшихся.\n\n"
        "Можно использовать подстановки: {title}, {date}, {time}, {datetime}, {link}."
    )


@router.message(HouseEventAdmin.waiting_broadcast_text, F.chat.type == "private")
async def event_broadcast_text_received(message: Message, state: FSMContext) -> None:
    """Принять текст рассылки."""
    if not is_admin(message.from_user.id):
        return
    error = _validate_text(message.text, max_len=3500, field_name="Текст рассылки")
    if error:
        await message.answer(error)
        return

    await state.update_data(broadcast_text=message.text.strip())
    await state.set_state(HouseEventAdmin.waiting_reminder_hours)
    await message.answer(
        "За сколько часов до начала напомнить записавшимся?\n\n"
        "Отправьте число часов, например: 3 или 1,5",
    )


@router.message(HouseEventAdmin.waiting_reminder_hours, F.chat.type == "private")
async def event_reminder_hours_received(message: Message, state: FSMContext) -> None:
    """Принять количество часов до основной рассылки."""
    if not is_admin(message.from_user.id):
        return

    raw_value = (message.text or "").strip()
    try:
        hours = float(raw_value.replace(",", "."))
    except ValueError:
        await message.answer("Напишите число часов, например: 3 или 1,5")
        return
    if not 0.25 <= hours <= 720:
        await message.answer("Укажите от 0,25 до 720 часов.")
        return

    data = await state.get_data()
    if "event_at" not in data:
        await state.clear()
        await message.answer("Создание мероприятия сброшено. Начните заново.")
        return

    event_at = datetime.fromisoformat(data["event_at"]).astimezone(settings.MOSCOW_TZ)
    reminder_at = event_at - timedelta(hours=hours)
    if reminder_at <= _now():
        await message.answer(
            "При таком количестве часов время напоминания уже прошло. "
            "Укажите меньшее число."
        )
        return

    await state.update_data(reminder_at=reminder_at.isoformat(timespec="seconds"))
    await message.answer(
        "Напомнить ли дополнительно за 15 минут до начала?",
        reply_markup=event_extra_reminder_keyboard,
    )


@router.callback_query(F.data.startswith("admin_event_extra_reminder:"))
async def event_extra_reminder_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохранить выбор дополнительного напоминания за 15 минут."""
    if not await _require_private_admin(callback):
        return

    data = await state.get_data()
    if "reminder_at" not in data:
        await state.clear()
        await _show_admin_home(callback, notice="Создание мероприятия сброшено. Начните заново.")
        return

    await state.update_data(remind_15_min=callback_value(callback.data) == "yes")
    await _safe_edit_or_answer(
        callback,
        "Добавить ссылку на встречу сейчас?",
        reply_markup=event_link_choice_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_link_choice:"))
async def event_link_choice(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбрать, добавлять ссылку сразу или позже."""
    if not await _require_private_admin(callback):
        return

    choice = callback_value(callback.data)
    if choice == "now":
        await state.set_state(HouseEventAdmin.waiting_initial_link)
        await _safe_edit_or_answer(callback, "Отправьте ссылку на встречу.")
        await callback.answer()
        return

    await _finish_event_creation_from_callback(callback, state, link=None)
    await callback.answer()


@router.message(HouseEventAdmin.waiting_initial_link, F.chat.type == "private")
async def event_initial_link_received(message: Message, state: FSMContext) -> None:
    """Принять ссылку при создании мероприятия."""
    if not is_admin(message.from_user.id):
        return
    error = _validate_text(message.text, max_len=500, field_name="Ссылка")
    if error:
        await message.answer(error)
        return
    await _finish_event_creation(message, state, link=message.text.strip())


@router.callback_query(F.data.startswith("admin_event_link:"))
async def start_event_link_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать текущую ссылку и начать подтверждаемое редактирование."""
    if not await _require_private_admin(callback): return
    event_id=_event_id_from_callback(callback); event=get_house_event(event_id)
    if event is None:
        await callback.answer("Мероприятие не найдено",show_alert=True); return
    current=event["link"] or "ссылка не задана"
    await state.clear(); await state.update_data(edit_event_id=event_id,edit_kind="link",old_value=event["link"] or "")
    await state.set_state(HouseEventAdmin.waiting_edit_link)
    await _safe_edit_or_answer(callback,f"Текущее значение:\n«{current}»\n\nОтправьте новое значение.",reply_markup=edit_prompt_keyboard(f"event_edit_cancel:{event_id}")); await callback.answer()


@router.message(HouseEventAdmin.waiting_edit_link, F.chat.type == "private")
async def event_link_edit_received(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id): return
    error=_validate_text(message.text,max_len=500,field_name="Ссылка")
    if error: await message.answer(error); return
    data=await state.get_data(); new=message.text.strip()
    await state.update_data(pending_value=new); await state.set_state(HouseEventAdmin.confirming_edit)
    await message.answer(f"Было:\n«{_edit_preview(data.get('old_value') or 'ссылка не задана')}»\n\nСтанет:\n«{_edit_preview(new)}»",reply_markup=edit_confirm_keyboard(save_callback=f"event_edit_save:{data['edit_event_id']}",retry_callback=f"event_edit_retry:{data['edit_event_id']}",cancel_callback=f"event_edit_cancel:{data['edit_event_id']}"))


@router.callback_query(F.data.startswith("admin_event_text:"))
async def start_event_text_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать текущий текст рассылки и начать подтверждаемое редактирование."""
    if not await _require_private_admin(callback): return
    event_id=_event_id_from_callback(callback); event=get_house_event(event_id)
    if event is None:
        await callback.answer("Мероприятие не найдено",show_alert=True); return
    current=event["broadcast_text"]
    await state.clear(); await state.update_data(edit_event_id=event_id,edit_kind="broadcast",old_value=current)
    await state.set_state(HouseEventAdmin.waiting_edit_broadcast_text)
    await _safe_edit_or_answer(callback,f"Текущее значение:\n«{current}»\n\nОтправьте новое значение.\nМожно использовать: {{title}}, {{date}}, {{time}}, {{datetime}}, {{link}}.",reply_markup=edit_prompt_keyboard(f"event_edit_cancel:{event_id}")); await callback.answer()


@router.message(HouseEventAdmin.waiting_edit_broadcast_text, F.chat.type == "private")
async def event_text_edit_received(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id): return
    error=_validate_text(message.text,max_len=3500,field_name="Текст рассылки")
    if error: await message.answer(error); return
    data=await state.get_data(); new=message.text.strip()
    await state.update_data(pending_value=new); await state.set_state(HouseEventAdmin.confirming_edit)
    await message.answer(f"Было:\n«{_edit_preview(data.get('old_value',''))}»\n\nСтанет:\n«{_edit_preview(new)}»",reply_markup=edit_confirm_keyboard(save_callback=f"event_edit_save:{data['edit_event_id']}",retry_callback=f"event_edit_retry:{data['edit_event_id']}",cancel_callback=f"event_edit_cancel:{data['edit_event_id']}"))


@router.callback_query(F.data.startswith("event_edit_save:"))
async def event_edit_save(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_private_admin(callback): return
    data=await state.get_data(); event_id=int(callback.data.split(":",1)[1]); value=data.get("pending_value")
    ok=(update_house_event_link(event_id,value) if data.get("edit_kind")=="link" else update_house_event_broadcast_text(event_id,value))
    await state.clear(); await callback.answer("Сохранено" if ok else "Не удалось сохранить",show_alert=not ok)
    await _send_admin_event_detail(callback.message,event_id)


@router.callback_query(F.data.startswith("event_edit_retry:"))
async def event_edit_retry(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_private_admin(callback): return
    data=await state.get_data(); event_id=int(callback.data.split(":",1)[1]); kind=data.get("edit_kind")
    await state.set_state(HouseEventAdmin.waiting_edit_link if kind=="link" else HouseEventAdmin.waiting_edit_broadcast_text)
    await _safe_edit_or_answer(callback,f"Текущее значение:\n«{data.get('old_value') or 'ссылка не задана'}»\n\nОтправьте новое значение.",reply_markup=edit_prompt_keyboard(f"event_edit_cancel:{event_id}")); await callback.answer()


@router.callback_query(F.data.startswith("event_edit_cancel:"))
async def event_edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_private_admin(callback): return
    event_id=int(callback.data.split(":",1)[1]); await state.clear(); await callback.answer("Изменения отменены")
    await _send_admin_event_detail(callback.message,event_id)


@router.callback_query(F.data.startswith("admin_event_participants:"))
async def show_event_participants(callback: CallbackQuery) -> None:
    """Показать список участников мероприятия."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    participants = get_house_event_registrations(event_id)
    if not participants:
        text = "👥 Пока никто не записался."
    else:
        lines = [f"👥 Участники: {len(participants)}"]
        for index, participant in enumerate(participants[:80], start=1):
            lines.append(f"{index}. {user_label(participant)}")
        if len(participants) > 80:
            lines.append(f"\n…и ещё {len(participants) - 80}.")
        text = "\n".join(lines)

    await _safe_edit_or_answer(
        callback,
        text,
        reply_markup=event_admin_back_to_detail_keyboard(event_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_test:"))
async def send_event_test(callback: CallbackQuery, bot: Bot) -> None:
    """Отправить тест рассылки текущему админу."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    event = get_house_event(event_id)
    if event is None:
        await callback.answer("Мероприятие не найдено.", show_alert=True)
        return

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=render_event_broadcast_text(event),
        disable_web_page_preview=False,
        reply_markup=restart_keyboard,
    )
    await callback.answer("Тест отправлен вам в личку.")


@router.callback_query(F.data.startswith("admin_event_send_now:"))
async def send_event_now(callback: CallbackQuery, bot: Bot) -> None:
    """Немедленно отправить рассылку записавшимся."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    await callback.answer("Запускаю рассылку…")
    sent, failed = await broadcast_house_event(bot, event_id, mark_sent=True)
    await _show_admin_event_detail(
        callback,
        event_id,
        notice=f"Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.",
    )


@router.callback_query(F.data.startswith("admin_event_cancel:"))
async def confirm_event_cancel(callback: CallbackQuery) -> None:
    """Попросить подтверждение отмены мероприятия."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    await _safe_edit_or_answer(
        callback,
        "❌ Отменить мероприятие?\n\nЗаписи участников сохранятся в архиве, но встреча исчезнет из активных.",
        reply_markup=confirm_event_cancel_keyboard(event_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_cancel_confirm:"))
async def cancel_event_confirmed(callback: CallbackQuery) -> None:
    """Отменить мероприятие после подтверждения."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    ok = cancel_house_event(event_id)
    await _show_admin_home(
        callback,
        notice="Мероприятие отменено." if ok else "Не удалось отменить мероприятие.",
    )


@router.callback_query(F.data.startswith("admin_event_delete:"))
async def confirm_event_delete(callback: CallbackQuery) -> None:
    """Попросить подтверждение безвозвратного удаления мероприятия."""
    if not await _require_private_admin(callback):
        return

    event_id = _event_id_from_callback(callback)
    event = get_house_event(event_id)
    if event is None:
        await _show_admin_home(callback, notice="Мероприятие не найдено.")
        return
    archived = not event_registration_is_open(event)
    await _safe_edit_or_answer(
        callback,
        "🗑 Удалить мероприятие навсегда?\n\n"
        "Будут удалены само мероприятие и все регистрации участников. Отменить это действие нельзя.",
        reply_markup=confirm_event_delete_keyboard(event_id, archived=archived),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_delete_confirm:"))
async def delete_event_confirmed(callback: CallbackQuery) -> None:
    """Безвозвратно удалить мероприятие после подтверждения."""
    if not await _require_private_admin(callback):
        return

    ok = delete_house_event(_event_id_from_callback(callback))
    await _show_admin_home(
        callback,
        notice="Мероприятие и все регистрации удалены." if ok else "Мероприятие уже удалено.",
    )
