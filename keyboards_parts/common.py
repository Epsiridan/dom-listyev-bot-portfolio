# -*- coding: utf-8 -*-
"""Общие inline-клавиатуры и маленькие фабрики кнопок."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def callback_button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def url_button(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def make_keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(contests=()) -> InlineKeyboardMarkup:
    """Собрать главное меню из активных конкурсов в базе."""
    rows = [
        [callback_button("🌿 Присоединиться к сообществу", "join_community")],
        [callback_button("🍃 Предложить пост для Дома Листьев", "propose_post_info")],
    ]
    for contest in contests:
        rows.append(
            [callback_button(str(contest["button_text"])[:64], f"contest_info:{contest['id']}")]
        )
    rows.extend(
        [
            [callback_button("📅 Мероприя Дома Листьев", "house_events")],
            [callback_button("🗂 Архив", "archive_menu")],
        ]
    )
    return make_keyboard(rows)


def admin_main_menu_keyboard(contests=()) -> InlineKeyboardMarkup:
    rows = list(main_menu_keyboard(contests).inline_keyboard)
    rows.append([callback_button("🛡 Администрация", "admin_panel")])
    return make_keyboard(rows)


restart_keyboard = make_keyboard([[callback_button("🏠 На главную", "main_menu")]])

rules_keyboard = make_keyboard(
    [
        [callback_button("📖 Открыть дверь", "accept_rules")],
        [callback_button("← Назад", "main_menu")],
    ]
)

admin_back_keyboard = make_keyboard(
    [
        [callback_button("← Администрация", "admin_panel")],
        [callback_button("🏠 На главную", "main_menu")],
    ]
)
