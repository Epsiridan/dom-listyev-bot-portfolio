# -*- coding: utf-8 -*-
"""Клавиатуры универсальных конкурсов и админского конструктора."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
)

from keyboards_parts.common import callback_button, make_keyboard, url_button
from services.contests import FILE_CATEGORY_LABELS, format_contest_datetime


def contest_info_keyboard(contest_id: int, *, has_criteria: bool, show_rules: bool) -> InlineKeyboardMarkup:
    rows = [[callback_button("📝 Подать заявку", f"contest_apply:{contest_id}")]]
    if has_criteria:
        rows.append([callback_button("⚖️ Критерии оценивания", f"contest_criteria:{contest_id}")])
    if show_rules:
        rows.append([callback_button("📖 Правила сообщества", f"contest_rules:{contest_id}")])
    rows.append([callback_button("← На главную", "main_menu")])
    return make_keyboard(rows)


def contest_back_keyboard(contest_id: int) -> InlineKeyboardMarkup:
    return make_keyboard([[callback_button("← К конкурсу", f"contest_info:{contest_id}")]])


def contest_subscription_keyboard(contest_id: int, channels) -> InlineKeyboardMarkup:
    rows = [[url_button(f"🌿 {channel['title']}", channel["url"])] for channel in channels]
    rows.extend(
        [
            [callback_button("✅ Я подписался", f"contest_sub_check:{contest_id}")],
            [callback_button("← К конкурсу", f"contest_info:{contest_id}")],
        ]
    )
    return make_keyboard(rows)


ai_keyboard = make_keyboard(
    [
        [callback_button("Да, использовался", "contest_ai:yes")],
        [callback_button("Нет, не использовался", "contest_ai:no")],
    ]
)


def submission_review_keyboard(contest_id: int) -> InlineKeyboardMarkup:
    return make_keyboard(
        [
            [callback_button("✅ Всё верно — перейти к работе", f"contest_confirm:{contest_id}")],
            [callback_button("🔄 Заполнить анкету заново", f"contest_restart:{contest_id}")],
        ]
    )


def work_format_keyboard(contest_id: int, mode: str) -> InlineKeyboardMarkup:
    rows = []
    if mode in {"text", "both"}:
        rows.append([callback_button("📝 Текстом в сообщении", f"contest_format:text:{contest_id}")])
    if mode in {"files", "both"}:
        rows.append([callback_button("📎 Файлом или медиа", f"contest_format:file:{contest_id}")])
    return make_keyboard(rows)


def finish_text_keyboard(contest_id: int) -> InlineKeyboardMarkup:
    return make_keyboard([[callback_button("✅ Завершить отправку", f"contest_finish_text:{contest_id}")]])


contest_admin_home_keyboard = make_keyboard(
    [
        [callback_button("➕ Создать конкурс", "admin_contest_create")],
        [callback_button("📋 Активные конкурсы", "admin_contest_active")],
        [callback_button("🕰 Архив конкурсов", "admin_contest_archive")],
        [callback_button("← Администрация", "admin_panel")],
    ]
)


def admin_contest_list_keyboard(contests, *, archive: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    prefix = "admin_contest_archive_view" if archive else "admin_contest_view"
    for contest in contests:
        rows.append(
            [callback_button(f"{format_contest_datetime(contest['ends_at'])[:10]} — {contest['title'][:34]}", f"{prefix}:{contest['id']}")]
        )
    rows.append([callback_button("← К администрированию конкурсов", "admin_contests")])
    return make_keyboard(rows)


def admin_contest_detail_keyboard(contest_id: int, *, active: bool) -> InlineKeyboardMarkup:
    rows = []
    if active:
        rows.append([callback_button("⏹ Закончить конкурс досрочно", f"admin_contest_finish:{contest_id}")])
        rows.append([callback_button("🗑 Удалить конкурс", f"admin_contest_delete:{contest_id}")])
        rows.append([callback_button("← К активным", "admin_contest_active")])
    else:
        rows.append([callback_button("🗑 Удалить конкурс", f"admin_contest_delete:{contest_id}")])
        rows.append([callback_button("← К архиву", "admin_contest_archive")])
    return make_keyboard(rows)


def confirm_contest_finish_keyboard(contest_id: int) -> InlineKeyboardMarkup:
    return make_keyboard(
        [
            [callback_button("Да, закончить", f"admin_contest_finish_confirm:{contest_id}")],
            [callback_button("← Отмена", f"admin_contest_view:{contest_id}")],
        ]
    )


def confirm_contest_delete_keyboard(contest_id: int, *, archived: bool) -> InlineKeyboardMarkup:
    back_callback = (
        f"admin_contest_archive_view:{contest_id}" if archived else f"admin_contest_view:{contest_id}"
    )
    return make_keyboard(
        [
            [callback_button("Да, удалить навсегда", f"admin_contest_delete_confirm:{contest_id}")],
            [callback_button("← Отмена", back_callback)],
        ]
    )


def yes_no_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return make_keyboard(
        [
            [callback_button("Да", f"{prefix}:yes"), callback_button("Нет", f"{prefix}:no")],
        ]
    )


contest_submission_mode_keyboard = make_keyboard(
    [
        [callback_button("📝 Только текст в боте", "admin_contest_mode:text")],
        [callback_button("📎 Только файлы / медиа", "admin_contest_mode:files")],
        [callback_button("📝📎 Текст или файлы", "admin_contest_mode:both")],
    ]
)


def contest_file_categories_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    selected_set = set(selected)
    for key, label in FILE_CATEGORY_LABELS.items():
        mark = "☑" if key in selected_set else "☐"
        rows.append([callback_button(f"{mark} {label}", f"admin_contest_file:{key}")])
    rows.append([callback_button("Далее →", "admin_contest_file_done")])
    return make_keyboard(rows)


contest_max_submissions_keyboard = make_keyboard(
    [
        [callback_button("1 работа", "admin_contest_max:1"), callback_button("2 работы", "admin_contest_max:2")],
        [callback_button("3 работы", "admin_contest_max:3")],
        [callback_button("Без ограничения", "admin_contest_max:none")],
    ]
)


contest_success_choice_keyboard = make_keyboard(
    [
        [callback_button("✅ Использовать стандартное", "admin_contest_success:default")],
        [callback_button("✍️ Написать своё", "admin_contest_success:custom")],
    ]
)


def destination_group_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🏠 Выбрать группу",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=7301,
                        chat_is_channel=False,
                        bot_is_member=True,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите группу для заявок",
    )


contest_topic_choice_keyboard = make_keyboard(
    [
        [callback_button("💬 В общий чат группы", "admin_contest_topic:none")],
        [callback_button("🗂 В отдельный топик", "admin_contest_topic:link")],
    ]
)


contest_preview_keyboard = make_keyboard(
    [[callback_button("🚀 Опубликовать конкурс", "admin_contest_publish")]]
)
