# -*- coding: utf-8 -*-
"""Пользовательский архив мероприятий и конкурсов."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from handlers.screens import safe_edit_or_answer
from keyboards import (
    archive_back_keyboard,
    archive_contest_detail_keyboard,
    archive_contests_keyboard,
    archive_event_detail_keyboard,
    archive_events_keyboard,
    archive_menu_keyboard,
)
from services.archive import (
    build_archived_contest_text,
    get_archived_contest,
    get_archived_contests,
    shorten_archive_description,
)
from services.database import (
    count_house_event_registrations,
    get_house_event,
    get_public_archived_house_events,
)
from services.events import format_event_datetime
from services.telegram_utils import callback_int_id, callback_value

router = Router()


def _build_archived_event_text(event, participants_count: int) -> str:
    """Собрать краткую публичную карточку проведённого мероприятия."""
    return (
        f"📅 {event['title']}\n\n"
        f"Когда: {format_event_datetime(event['event_at'])}\n\n"
        f"{shorten_archive_description(event['description'])}\n\n"
        f"Было участников: {participants_count}"
    )


@router.callback_query(F.data == "archive_menu")
async def show_archive_menu(callback: CallbackQuery) -> None:
    """Открыть главный экран публичного архива."""
    await safe_edit_or_answer(
        callback,
        "🗂 Архив Дома Листьев\n\nЗдесь собираются прошедшие мероприятия и завершённые конкурсы.",
        reply_markup=archive_menu_keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "archive_events")
async def show_archive_events(callback: CallbackQuery) -> None:
    """Показать список проведённых мероприятий."""
    events = get_public_archived_house_events()
    if events:
        text = "📅 Архив мероприятий\n\nВыберите событие:"
    else:
        text = "📅 Архив мероприятий\n\nПока здесь нет проведённых мероприятий."

    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=archive_events_keyboard(events),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("archive_event_view:"))
async def show_archive_event_detail(callback: CallbackQuery) -> None:
    """Открыть краткую карточку проведённого мероприятия."""
    event_id = callback_int_id(callback.data)
    event = get_house_event(event_id)
    public_events = {event["id"] for event in get_public_archived_house_events(limit=100)}

    if event is None or event_id not in public_events:
        await safe_edit_or_answer(
            callback,
            "Мероприятие не найдено в публичном архиве.",
            reply_markup=archive_back_keyboard,
        )
        await callback.answer()
        return

    await safe_edit_or_answer(
        callback,
        _build_archived_event_text(
            event,
            participants_count=count_house_event_registrations(event_id),
        ),
        reply_markup=archive_event_detail_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "archive_contests")
async def show_archive_contests(callback: CallbackQuery) -> None:
    """Показать список завершённых конкурсов."""
    contests = get_archived_contests()
    if contests:
        text = "🎨 Архив конкурсов\n\nВыберите конкурс:"
    else:
        text = "🎨 Архив конкурсов\n\nПока здесь нет завершённых конкурсов."

    await safe_edit_or_answer(
        callback,
        text,
        reply_markup=archive_contests_keyboard(contests),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("archive_contest_view:"))
async def show_archive_contest_detail(callback: CallbackQuery) -> None:
    """Открыть краткую карточку завершённого конкурса."""
    contest = get_archived_contest(callback_value(callback.data))
    if contest is None:
        await safe_edit_or_answer(
            callback,
            "Конкурс не найден в публичном архиве.",
            reply_markup=archive_back_keyboard,
        )
        await callback.answer()
        return

    await safe_edit_or_answer(
        callback,
        build_archived_contest_text(contest),
        reply_markup=archive_contest_detail_keyboard(),
    )
    await callback.answer()
