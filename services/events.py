# -*- coding: utf-8 -*-
"""Сервис мероприятий Дома Листьев.

Модуль держит форматирование, подстановки в тексты и безопасную фоновую
рассылку отдельно от Telegram-обработчиков.
"""

import asyncio
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from services.content import get_text
from services.database import (
    get_due_house_event_15_min_reminders,
    get_due_house_events,
    get_house_event,
    get_house_event_registrations,
    mark_house_event_reminder_sent,
)

HOME_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🏠 На главную",
                callback_data="main_menu",
            )
        ]
    ]
)


def parse_moscow_datetime(value: str) -> datetime:
    """Разобрать дату/время в формате `ДД.ММ.ГГГГ ЧЧ:ММ` как московское время."""
    parsed = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")
    return parsed.replace(tzinfo=settings.MOSCOW_TZ)


def parse_moscow_date(value: str) -> datetime:
    """Разобрать дату `ДД.ММ.ГГГГ` как московскую дату без времени."""
    parsed = datetime.strptime(value.strip(), "%d.%m.%Y")
    return parsed.replace(tzinfo=settings.MOSCOW_TZ)


def parse_moscow_time(value: str) -> tuple[int, int]:
    """Разобрать время `ЧЧ:ММ`."""
    parsed = datetime.strptime(value.strip(), "%H:%M")
    return parsed.hour, parsed.minute


def format_event_datetime(value: str | None) -> str:
    """Показать ISO-дату мероприятия в формате для человека."""
    if not value:
        return "не указано"
    try:
        event_at = datetime.fromisoformat(value).astimezone(settings.MOSCOW_TZ)
    except ValueError:
        return value
    return event_at.strftime("%d.%m.%Y %H:%M МСК")


def short_event_datetime(value: str | None) -> str:
    """Короткая дата для кнопок."""
    if not value:
        return "без даты"
    try:
        event_at = datetime.fromisoformat(value).astimezone(settings.MOSCOW_TZ)
    except ValueError:
        return value
    return event_at.strftime("%d.%m %H:%M")


def render_event_broadcast_text(event) -> str:
    """Подставить данные мероприятия в админский шаблон рассылки."""
    event_at = datetime.fromisoformat(event["event_at"]).astimezone(settings.MOSCOW_TZ)
    link = event["link"] or "ссылка будет добавлена позже"
    replacements = {
        "{title}": event["title"],
        "{date}": event_at.strftime("%d.%m.%Y"),
        "{time}": event_at.strftime("%H:%M"),
        "{datetime}": format_event_datetime(event["event_at"]),
        "{link}": link,
    }
    text = event["broadcast_text"]
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def build_event_public_text(event, *, registered_count: int | None = None) -> str:
    """Собрать карточку мероприятия для пользователей."""
    count_line = ""
    if registered_count is not None:
        count_line = f"\n\nЗаписались: {registered_count}"

    return (
        f"{get_text('event_public_intro')}\n\n"
        f"{event['title']}\n\n"
        f"Когда: {format_event_datetime(event['event_at'])}\n\n"
        f"{event['description']}"
        f"{count_line}"
    )


def build_event_admin_text(event, *, registered_count: int) -> str:
    """Собрать админскую карточку мероприятия."""
    reminder = format_event_datetime(event["reminder_at"]) if event["reminder_at"] else "без авторассылки"
    link = event["link"] or "не добавлена"
    sent = format_event_datetime(event["reminder_sent_at"]) if event["reminder_sent_at"] else "ещё не отправлялась"
    extra_reminder = "да" if event["remind_15_min"] else "нет"
    extra_sent = (
        format_event_datetime(event["reminder_15_sent_at"])
        if event["reminder_15_sent_at"]
        else "ещё не отправлялось"
    )
    return (
        f"🛠 Мероприятие #{event['id']}\n\n"
        f"Название: {event['title']}\n"
        f"Дата: {format_event_datetime(event['event_at'])}\n"
        f"Записались: {registered_count}\n"
        f"Ссылка: {link}\n"
        f"Рассылка: {reminder}\n"
        f"Статус рассылки: {sent}\n\n"
        f"Дополнительно за 15 минут: {extra_reminder}\n"
        f"Статус напоминания за 15 минут: {extra_sent}\n\n"
        f"Описание:\n{event['description']}"
    )


def user_label(row) -> str:
    """Читаемое имя участника из строки регистрации."""
    username = row["username"]
    if username:
        return f"@{username}"
    full_name = row["full_name"]
    if full_name:
        return full_name
    return f"id{row['user_id']}"


async def broadcast_house_event(
    bot: Bot,
    event_id: int,
    *,
    mark_sent: bool = True,
    fifteen_minute: bool = False,
) -> tuple[int, int]:
    """Отправить текст мероприятия всем активным участникам.

    Возвращает пару: (успешно отправлено, ошибок). Исключения отдельных
    пользователей не роняют всю рассылку и фоновый планировщик.
    """
    event = get_house_event(event_id)
    if event is None or event["status"] != "active":
        return 0, 0

    text = render_event_broadcast_text(event)
    sent_count = 0
    failed_count = 0

    for participant in get_house_event_registrations(event_id):
        try:
            await bot.send_message(
                chat_id=participant["user_id"],
                text=text,
                disable_web_page_preview=False,
                reply_markup=HOME_KEYBOARD,
            )
            sent_count += 1
        except Exception as error:
            failed_count += 1
            print(
                "event broadcast failed: "
                f"event_id={event_id} user_id={participant['user_id']} error={error!r}"
            )
        await asyncio.sleep(0.05)

    if mark_sent:
        mark_house_event_reminder_sent(event_id, fifteen_minute=fifteen_minute)

    return sent_count, failed_count


async def send_due_house_event_reminders(bot: Bot) -> None:
    """Отправить все наступившие рассылки мероприятий."""
    for event in get_due_house_events(limit=3):
        await broadcast_house_event(bot, event["id"], mark_sent=True)
    for event in get_due_house_event_15_min_reminders(limit=3):
        await broadcast_house_event(
            bot,
            event["id"],
            mark_sent=True,
            fifteen_minute=True,
        )


def should_send_link_after_registration(event, *, now: datetime | None = None) -> bool:
    """Нужно ли немедленно прислать ссылку поздно записавшемуся участнику."""
    if not event["link"]:
        return False
    current = now or datetime.now(settings.MOSCOW_TZ)
    event_at = datetime.fromisoformat(event["event_at"]).astimezone(settings.MOSCOW_TZ)
    return event_at - timedelta(minutes=15) < current <= event_at + timedelta(minutes=30)


def event_registration_is_open(event, *, now: datetime | None = None) -> bool:
    """Проверить 30-минутное окно записи после начала мероприятия."""
    if event["status"] != "active":
        return False
    current = now or datetime.now(settings.MOSCOW_TZ)
    event_at = datetime.fromisoformat(event["event_at"]).astimezone(settings.MOSCOW_TZ)
    return current <= event_at + timedelta(minutes=30)


async def send_link_after_late_registration(bot: Bot, event, user_id: int) -> None:
    """Сразу отправить поздно записавшемуся участнику ссылку на встречу."""
    await bot.send_message(
        chat_id=user_id,
        text=(
            f"⏰ Встреча «{event['title']}» скоро начнётся или уже идёт.\n\n"
            f"Ссылка: {event['link']}"
        ),
        disable_web_page_preview=False,
        reply_markup=HOME_KEYBOARD,
    )


async def house_event_reminder_loop(bot: Bot) -> None:
    """Бесконечный планировщик рассылок мероприятий."""
    while True:
        try:
            await send_due_house_event_reminders(bot)
        except Exception as error:
            print(f"house_event_reminder_loop error: {error!r}")
        await asyncio.sleep(60)
