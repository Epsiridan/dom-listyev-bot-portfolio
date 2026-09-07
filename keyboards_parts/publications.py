# -*- coding: utf-8 -*-
"""Клавиатуры пользовательской предложки, модерации и очереди публикаций."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards_parts.common import callback_button, make_keyboard


# Подтверждение правил перед отправкой поста в предложку.
propose_post_rules_keyboard = make_keyboard(
    [
        [callback_button("✅ Согласен, хочу предложить пост", "propose_post_accept_rules")],
        [callback_button("← Назад", "main_menu")],
    ]
)

# Выбор творческой группы можно пропустить одной кнопкой.
creative_group_keyboard = make_keyboard([[callback_button("Без творческой группы", "proposed_skip_creative_group")]])

# Пользователь решает, показывать ли автора в канальной публикации.
author_visibility_keyboard = make_keyboard(
    [
        [callback_button("Да, указать автора", "proposed_author_yes")],
        [callback_button("Нет, опубликовать анонимно", "proposed_author_no")],
    ]
)


def proposed_post_review_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Кнопки модерации конкретного листа в админской предложке."""
    return make_keyboard(
        [
            [callback_button("✅ Одобрить в очередь", f"proposed_approve:{post_id}")],
            [callback_button("🚀 Опубликовать сейчас", f"proposed_publish_now:{post_id}")],
            [callback_button("✏️ Поправить текст", f"proposed_edit:{post_id}")],
            [callback_button("❌ Отклонить", f"proposed_reject:{post_id}")],
        ]
    )


def publication_queue_keyboard(posts) -> InlineKeyboardMarkup:
    """Построить админскую клавиатуру для очереди публикаций."""
    rows: list[list[InlineKeyboardButton]] = []

    for post in posts:
        post_id = post["id"]
        link = proposed_post_review_link(post)
        if link:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🔎 Лист #{post_id} в предложке",
                        url=link,
                    )
                ]
            )
        rows.append([callback_button(f"🗑 Удалить лист #{post_id}", f"admin_queue_delete:{post_id}")])

    rows.append([callback_button("🔄 Обновить", "admin_publication_queue")])
    rows.append([callback_button("← Администрация", "admin_panel")])
    return make_keyboard(rows)


def confirm_queue_delete_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления листа из очереди с последующим сдвигом."""
    return make_keyboard(
        [
            [callback_button("✅ Да, удалить", f"admin_queue_delete_confirm:{post_id}")],
            [callback_button("← Назад к очереди", "admin_publication_queue")],
        ]
    )


def proposed_post_review_link(post) -> str | None:
    """Собрать t.me/c ссылку на сообщение в приватной админской группе."""
    chat_id = post["admin_chat_id"]
    message_id = post["admin_message_id"]
    if not chat_id or not message_id:
        return None
    if chat_id < -1000000000000:
        internal_id = abs(chat_id) - 1000000000000
        return f"https://t.me/c/{internal_id}/{message_id}"
    return None
