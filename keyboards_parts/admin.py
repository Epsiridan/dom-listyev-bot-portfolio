# -*- coding: utf-8 -*-
"""Клавиатуры единого админского раздела."""

from keyboards_parts.common import callback_button, make_keyboard


admin_panel_keyboard = make_keyboard(
    [
        [callback_button("🎨 Тексты и оформление", "admin_content")],
        [callback_button("🗓 Очередь публикаций", "admin_publication_queue")],
        [callback_button("🛠 Администрация мероприятий", "admin_house_events")],
        [callback_button("🎨 Администрация конкурсов", "admin_contests")],
        [callback_button("🧾 Конкурсные заявки", "admin_submission_tools")],
        [callback_button("🧹 Очистка опубликованных листов", "admin_cleanup_tools")],
        [callback_button("🆔 Диагностика ID", "admin_diagnostics")],
        [callback_button("← Главное меню", "main_menu")],
    ]
)

admin_submission_tools_keyboard = make_keyboard(
    [
        [callback_button("🔄 Сбросить мои тестовые заявки", "admin_reset_my_submission")],
        [callback_button("🗑 Удалить заявки пользователя", "admin_delete_submission")],
        [callback_button("⚠️ Очистить все заявки", "admin_clear_submissions")],
        [callback_button("← Администрация", "admin_panel")],
    ]
)

confirm_clear_submissions_keyboard = make_keyboard(
    [
        [callback_button("Да, очистить все заявки", "admin_clear_submissions_confirm")],
        [callback_button("← Отмена", "admin_submission_tools")],
    ]
)

cleanup_published_keyboard = make_keyboard(
    [
        [
            callback_button("30 дней", "admin_cleanup_published:30"),
            callback_button("60 дней", "admin_cleanup_published:60"),
            callback_button("90 дней", "admin_cleanup_published:90"),
        ],
        [callback_button("← Администрация", "admin_panel")],
    ]
)
