# -*- coding: utf-8 -*-
"""Совместимый фасад inline-клавиатур.

Реальные блоки лежат в `keyboards_parts/`, но обработчики продолжают импортировать
клавиатуры из `keyboards`, чтобы рефакторинг не менял публичный API проекта.
"""

from keyboards_parts.admin import (
    admin_panel_keyboard,
    admin_submission_tools_keyboard,
    cleanup_published_keyboard,
    confirm_clear_submissions_keyboard,
)
from keyboards_parts.archive import (
    archive_back_keyboard,
    archive_contest_detail_keyboard,
    archive_contests_keyboard,
    archive_event_detail_keyboard,
    archive_events_keyboard,
    archive_menu_keyboard,
)
from keyboards_parts.common import (
    admin_back_keyboard,
    admin_main_menu_keyboard,
    main_menu_keyboard,
    restart_keyboard,
    rules_keyboard,
)
from keyboards_parts.contest import (
    admin_contest_detail_keyboard,
    admin_contest_list_keyboard,
    ai_keyboard,
    confirm_contest_delete_keyboard,
    confirm_contest_finish_keyboard,
    contest_admin_home_keyboard,
    contest_back_keyboard,
    contest_file_categories_keyboard,
    contest_info_keyboard,
    contest_max_submissions_keyboard,
    contest_preview_keyboard,
    contest_submission_mode_keyboard,
    contest_subscription_keyboard,
    contest_success_choice_keyboard,
    contest_topic_choice_keyboard,
    destination_group_keyboard,
    finish_text_keyboard,
    submission_review_keyboard,
    work_format_keyboard,
    yes_no_keyboard,
)
from keyboards_parts.events import (
    confirm_event_cancel_keyboard,
    confirm_event_delete_keyboard,
    event_admin_back_to_detail_keyboard,
    event_admin_archive_detail_keyboard,
    event_admin_detail_keyboard,
    event_admin_events_keyboard,
    event_admin_home_keyboard,
    event_link_choice_keyboard,
    event_extra_reminder_keyboard,
    house_event_detail_keyboard,
    house_events_keyboard,
)
from keyboards_parts.publications import (
    author_visibility_keyboard,
    confirm_queue_delete_keyboard,
    creative_group_keyboard,
    propose_post_rules_keyboard,
    proposed_post_review_link,
    proposed_post_review_keyboard,
    publication_queue_keyboard,
)

from keyboards_parts.content import (content_cancel_keyboard, content_confirm_keyboard, content_detail_keyboard, content_list_keyboard, content_mode_keyboard, content_reset_confirm_keyboard)
