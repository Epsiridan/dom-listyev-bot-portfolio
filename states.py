# -*- coding: utf-8 -*-
"""FSM-состояния пользовательских сценариев.

Состояния описывают, какой следующий ввод бот ждёт от пользователя. Это
позволяет обработчикам быть простыми и не хранить прогресс в глобальных
переменных.
"""

from aiogram.fsm.state import State, StatesGroup


class ContestSubmission(StatesGroup):
    """Пошаговая форма подачи конкурсной работы."""

    waiting_subscription = State()
    waiting_author = State()
    waiting_title = State()
    waiting_repost = State()
    waiting_ai_choice = State()
    waiting_ai_link = State()
    reviewing_info = State()
    editing_info_field = State()
    waiting_format = State()
    waiting_text_work = State()
    waiting_file_work = State()


class ProposedPostSubmission(StatesGroup):
    """Пошаговая форма пользовательской предложки в канал."""

    waiting_content = State()
    waiting_creative_group = State()
    waiting_author_visibility = State()


class ProposedPostModeration(StatesGroup):
    """Админский сценарий редактирования текста предложенного поста."""

    waiting_edited_text = State()
    confirming_edit = State()


class AdminMaintenance(StatesGroup):
    """Админские сценарии обслуживания из кнопочного раздела."""

    waiting_submission_ref = State()


class HouseEventAdmin(StatesGroup):
    """Пошаговое создание и редактирование мероприятий Дома Листьев."""

    waiting_title = State()
    waiting_description = State()
    waiting_date = State()
    waiting_time = State()
    waiting_broadcast_text = State()
    waiting_reminder_hours = State()
    waiting_initial_link = State()
    waiting_edit_link = State()
    waiting_edit_broadcast_text = State()
    confirming_edit = State()


class ContestAdmin(StatesGroup):
    """Пошаговый админский конструктор конкурсов."""

    waiting_title = State()
    waiting_description = State()
    waiting_start = State()
    waiting_end = State()
    waiting_criteria = State()
    waiting_channels = State()
    choosing_files = State()
    waiting_success_message = State()
    waiting_destination_chat = State()
    waiting_topic_link = State()
    reviewing = State()


class ContentAdmin(StatesGroup):
    """Редактор базовых текстов и изображений с отложенным сохранением."""

    waiting_text = State()
    waiting_image = State()
    confirming = State()
