# -*- coding: utf-8 -*-
"""Клавиатуры редактора базового контента."""
from keyboards_parts.common import callback_button, make_keyboard


def content_list_keyboard(blocks):
    rows=[[callback_button(block.title[:48], f"content_view:{block.key}")] for block in blocks]
    rows.append([callback_button("← Администрация", "admin_panel")])
    return make_keyboard(rows)


def content_detail_keyboard(key: str, *, has_image: bool, is_custom: bool):
    rows=[
        [callback_button("✏️ Изменить текст", f"content_text:{key}")],
        [callback_button("🖼 Заменить изображение" if has_image else "🖼 Добавить изображение", f"content_image:{key}")],
    ]
    if has_image:
        rows.append([callback_button("🗑 Удалить изображение", f"content_image_delete:{key}")])
    rows.append([callback_button("⚙️ Режим отправки", f"content_mode:{key}")])
    rows.append([callback_button("👁 Предпросмотр", f"content_preview:{key}")])
    if is_custom:
        rows.append([callback_button("↩️ Сбросить к стандартному", f"content_reset:{key}")])
    rows.append([callback_button("← К списку текстов", "admin_content")])
    return make_keyboard(rows)


def content_cancel_keyboard(key: str):
    return make_keyboard([[callback_button("Отмена", f"content_cancel:{key}")]])


def content_confirm_keyboard(key: str):
    return make_keyboard([
        [callback_button("Сохранить", f"content_save:{key}")],
        [callback_button("Ввести заново", f"content_retry:{key}")],
        [callback_button("Отмена", f"content_cancel:{key}")],
    ])


def content_mode_keyboard(key: str):
    return make_keyboard([
        [callback_button("Автоматически", f"content_mode_pick:{key}:auto")],
        [callback_button("Только текст", f"content_mode_pick:{key}:text")],
        [callback_button("Фото с подписью", f"content_mode_pick:{key}:caption")],
        [callback_button("Фото, затем текст", f"content_mode_pick:{key}:separate")],
        [callback_button("Отмена", f"content_cancel:{key}")],
    ])


def content_reset_confirm_keyboard(key: str):
    return make_keyboard([
        [callback_button("Сбросить", f"content_reset_confirm:{key}")],
        [callback_button("Отмена", f"content_cancel:{key}")],
    ])
