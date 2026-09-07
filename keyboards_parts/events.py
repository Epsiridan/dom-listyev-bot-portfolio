# -*- coding: utf-8 -*-
"""Клавиатуры пользовательских и админских сценариев мероприятий."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards_parts.common import callback_button, make_keyboard
from services.events import short_event_datetime


def house_events_keyboard(events, *, back_callback: str = "main_menu") -> InlineKeyboardMarkup:
    """Список мероприятий для обычных пользователей."""
    rows: list[list[InlineKeyboardButton]] = []
    for event in events:
        rows.append(
            [
                callback_button(
                    f"{short_event_datetime(event['event_at'])} — {event['title'][:32]}",
                    f"house_event_view:{event['id']}",
                )
            ]
        )
    rows.append([callback_button("← Назад", back_callback)])
    return make_keyboard(rows)


def house_event_detail_keyboard(event_id: int, *, is_registered: bool) -> InlineKeyboardMarkup:
    """Кнопки карточки мероприятия для пользователя."""
    action = callback_button(
        "❌ Отменить запись" if is_registered else "✅ Записаться",
        f"house_event_unregister:{event_id}" if is_registered else f"house_event_register:{event_id}",
    )
    return make_keyboard(
        [
            [action],
            [callback_button("← К мероприятиям", "house_events")],
        ]
    )


event_admin_home_keyboard = make_keyboard(
    [
        [callback_button("➕ Создать мероприятие", "admin_event_create")],
        [callback_button("📋 Активные мероприятия", "admin_event_active")],
        [callback_button("🕰 Архив мероприятий", "admin_event_archive")],
        [callback_button("← Назад", "admin_panel")],
    ]
)


def event_admin_events_keyboard(events, *, archive: bool = False) -> InlineKeyboardMarkup:
    """Список мероприятий для админа."""
    rows: list[list[InlineKeyboardButton]] = []
    callback_prefix = "admin_event_archive_view" if archive else "admin_event_view"
    for event in events:
        rows.append(
            [
                callback_button(
                    f"{short_event_datetime(event['event_at'])} — {event['title'][:30]}",
                    f"{callback_prefix}:{event['id']}",
                )
            ]
        )
    rows.append([callback_button("← К администрации мероприятий", "admin_house_events")])
    return make_keyboard(rows)


def event_admin_detail_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления одним мероприятием."""
    return make_keyboard(
        [
            [callback_button("🔗 Добавить/изменить ссылку", f"admin_event_link:{event_id}")],
            [callback_button("📨 Изменить текст рассылки", f"admin_event_text:{event_id}")],
            [callback_button("👥 Список участников", f"admin_event_participants:{event_id}")],
            [callback_button("🧪 Отправить тест мне", f"admin_event_test:{event_id}")],
            [callback_button("🚀 Отправить сейчас", f"admin_event_send_now:{event_id}")],
            [callback_button("❌ Отменить мероприятие", f"admin_event_cancel:{event_id}")],
            [callback_button("🗑 Удалить мероприятие", f"admin_event_delete:{event_id}")],
            [callback_button("← К активным мероприятиям", "admin_event_active")],
        ]
    )


def event_admin_back_to_detail_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Возврат к карточке мероприятия."""
    return make_keyboard([[callback_button("← К мероприятию", f"admin_event_view:{event_id}")]])


def event_admin_archive_detail_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Возврат из архивной карточки без действий редактирования."""
    return make_keyboard(
        [
            [callback_button("🗑 Удалить мероприятие", f"admin_event_delete:{event_id}")],
            [callback_button("← К архиву мероприятий", "admin_event_archive")],
            [callback_button("← К администрации мероприятий", "admin_house_events")],
        ]
    )


event_extra_reminder_keyboard = make_keyboard(
    [
        [
            callback_button("✅ Да", "admin_event_extra_reminder:yes"),
            callback_button("❌ Нет", "admin_event_extra_reminder:no"),
        ],
    ]
)


event_link_choice_keyboard = make_keyboard(
    [
        [
            callback_button("✅ Добавить сейчас", "admin_event_link_choice:now"),
            callback_button("⏳ Позже", "admin_event_link_choice:later"),
        ]
    ]
)


def confirm_event_cancel_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Подтверждение отмены мероприятия."""
    return make_keyboard(
        [
            [callback_button("Да, отменить", f"admin_event_cancel_confirm:{event_id}")],
            [callback_button("← Назад", f"admin_event_view:{event_id}")],
        ]
    )


def confirm_event_delete_keyboard(event_id: int, *, archived: bool) -> InlineKeyboardMarkup:
    """Подтверждение безвозвратного удаления мероприятия."""
    back_callback = (
        f"admin_event_archive_view:{event_id}" if archived else f"admin_event_view:{event_id}"
    )
    return make_keyboard(
        [
            [callback_button("Да, удалить навсегда", f"admin_event_delete_confirm:{event_id}")],
            [callback_button("← Отмена", back_callback)],
        ]
    )
