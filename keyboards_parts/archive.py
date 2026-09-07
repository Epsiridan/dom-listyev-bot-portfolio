# -*- coding: utf-8 -*-
"""Клавиатуры пользовательского архива Дома Листьев."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards_parts.common import callback_button, make_keyboard
from services.events import short_event_datetime


archive_menu_keyboard = make_keyboard(
    [
        [callback_button("📅 Мероприятия", "archive_events")],
        [callback_button("🎨 Конкурсы", "archive_contests")],
        [callback_button("← Назад", "main_menu")],
    ]
)

archive_back_keyboard = make_keyboard(
    [
        [callback_button("← В архив", "archive_menu")],
        [callback_button("🏠 На главную", "main_menu")],
    ]
)


def archive_events_keyboard(events) -> InlineKeyboardMarkup:
    """Список прошедших мероприятий для публичного архива."""
    rows: list[list[InlineKeyboardButton]] = []
    for event in events:
        rows.append(
            [
                callback_button(
                    f"{short_event_datetime(event['event_at'])} — {event['title'][:32]}",
                    f"archive_event_view:{event['id']}",
                )
            ]
        )
    rows.append([callback_button("← В архив", "archive_menu")])
    return make_keyboard(rows)


def archive_event_detail_keyboard() -> InlineKeyboardMarkup:
    """Возврат из карточки архивного мероприятия."""
    return make_keyboard(
        [
            [callback_button("← К мероприятиям архива", "archive_events")],
            [callback_button("← В архив", "archive_menu")],
        ]
    )


def archive_contests_keyboard(contests: list[dict]) -> InlineKeyboardMarkup:
    """Список прошедших конкурсов для публичного архива."""
    rows: list[list[InlineKeyboardButton]] = []
    for contest in contests:
        rows.append(
            [
                callback_button(
                    contest["button_text"],
                    f"archive_contest_view:{contest['id']}",
                )
            ]
        )
    rows.append([callback_button("← В архив", "archive_menu")])
    return make_keyboard(rows)


def archive_contest_detail_keyboard() -> InlineKeyboardMarkup:
    """Возврат из карточки архивного конкурса."""
    return make_keyboard(
        [
            [callback_button("← К конкурсам архива", "archive_contests")],
            [callback_button("← В архив", "archive_menu")],
        ]
    )
