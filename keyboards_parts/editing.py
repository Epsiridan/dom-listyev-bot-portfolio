# -*- coding: utf-8 -*-
"""Общие кнопки подтверждения изменения существующего значения."""
from keyboards_parts.common import callback_button, make_keyboard


def edit_prompt_keyboard(cancel_callback: str):
    return make_keyboard([[callback_button("Отмена", cancel_callback)]])


def edit_confirm_keyboard(*, save_callback: str, retry_callback: str, cancel_callback: str):
    return make_keyboard([
        [callback_button("Сохранить", save_callback)],
        [callback_button("Ввести заново", retry_callback)],
        [callback_button("Отмена", cancel_callback)],
    ])
