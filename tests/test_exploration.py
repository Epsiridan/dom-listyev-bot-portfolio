import os
import unittest
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import EditMessageText, SendMessage

from config import settings
from handlers import exploration as exploration_handler
from services.exploration import (
    EXPECTED_RARITY_COUNTS,
    OBSERVATION_TABLES,
    ROOM_NAME_MAX_LENGTH,
    SPECIAL_ROOM_POOLS,
    ExplorationReport,
    choose_exploration_report,
    choose_revisit_note,
    extract_room_name,
    format_exploration_report,
    format_remaining_cooldown,
    get_cooldown_remaining,
    normalize_room_name,
)
from services.telegram_utils import call_telegram_with_retry


class ExplorationServiceTests(unittest.TestCase):
    def test_each_general_table_has_25_expected_variants(self) -> None:
        for table_name, options in OBSERVATION_TABLES.items():
            with self.subTest(table=table_name):
                self.assertEqual(len(options), 25)
                self.assertEqual(
                    Counter(option.rarity for option in options),
                    Counter(EXPECTED_RARITY_COUNTS),
                )

    def test_extract_room_name_normalizes_spaces_and_bot_suffix(self) -> None:
        self.assertEqual(
            extract_room_name("/исследовать@DomListyevBot   комнату   Архив   №7 "),
            "Архив №7",
        )

    def test_extract_room_name_rejects_other_text_and_requires_name(self) -> None:
        self.assertIsNone(extract_room_name("исследовать комнату Архив"))
        self.assertEqual(extract_room_name("/исследовать комнату"), "")

    def test_extract_room_name_is_limited(self) -> None:
        room_name = extract_room_name("/исследовать комнату " + "я" * 200)
        self.assertEqual(len(room_name), ROOM_NAME_MAX_LENGTH)

    def test_special_rooms_are_normalized_with_aliases(self) -> None:
        workshop = normalize_room_name("  «МАСТЕРСКУЮ» ")
        hall = normalize_room_name("холл")
        hall_alias = normalize_room_name("зал")
        bedroom = normalize_room_name("Спальня")

        self.assertEqual(
            (workshop.key, workshop.display_name, workshop.special_key),
            ("special:workshop", "Мастерская", "workshop"),
        )
        self.assertEqual(hall.special_key, "hall")
        self.assertEqual(hall_alias.special_key, "hall")
        self.assertEqual(bedroom.special_key, "bedroom")

    def test_general_room_names_merge_case_and_spaces(self) -> None:
        first = normalize_room_name("Архив   №7")
        second = normalize_room_name(" архив №7 ")
        self.assertEqual(first.key, second.key)

    def test_special_room_report_always_contains_special_detail(self) -> None:
        room = normalize_room_name("Мастерская")
        special_texts = {
            option.text
            for options in SPECIAL_ROOM_POOLS["workshop"].values()
            for option in options
        }

        for _ in range(20):
            report = choose_exploration_report(room)
            self.assertTrue(
                {report.space, report.traces, report.response} & special_texts
            )

    def test_revisit_note_works_only_for_48_hours(self) -> None:
        now = datetime(2026, 7, 13, 12, 0, tzinfo=settings.MOSCOW_TZ)
        recent = (now - timedelta(hours=47)).isoformat()
        expired = (now - timedelta(hours=49)).isoformat()

        self.assertIsNotNone(choose_revisit_note(recent, now=now))
        self.assertIsNone(choose_revisit_note(expired, now=now))

    def test_formatted_report_contains_three_aspects_and_note(self) -> None:
        room = normalize_room_name("Холл")
        report = ExplorationReport(
            space="Пространство.",
            traces="Следы.",
            response="Отклик.",
            revisit_note="Последствие.",
        )
        text = format_exploration_report(room, report)

        self.assertIn("Пространство: Пространство.", text)
        self.assertIn("Следы: Следы.", text)
        self.assertIn("Отклик Дома: Отклик.", text)
        self.assertIn("Приписка смотрителя: Последствие.", text)

    def test_format_remaining_cooldown_rounds_up(self) -> None:
        self.assertEqual(
            format_remaining_cooldown(timedelta(hours=1, seconds=1)),
            "1 ч. 1 мин.",
        )

    def test_invalid_timestamp_does_not_crash(self) -> None:
        self.assertIsNone(get_cooldown_remaining("not-an-iso-date"))

    def test_legacy_naive_timestamp_uses_moscow_time(self) -> None:
        now = datetime(2026, 7, 13, 12, 0, tzinfo=settings.MOSCOW_TZ)
        last_explored = datetime(2026, 7, 13, 10, 0).isoformat()
        self.assertEqual(
            get_cooldown_remaining(last_explored, now=now),
            timedelta(hours=4),
        )


class TelegramRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_network_error_is_retried(self) -> None:
        error = TelegramNetworkError(
            method=SendMessage(chat_id=1, text="test"),
            message="temporary failure",
        )
        operation = AsyncMock(side_effect=[error, "ok"])

        with patch(
            "services.telegram_utils.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = await call_telegram_with_retry(
                operation,
                operation_name="test operation",
            )

        self.assertEqual(result, "ok")
        self.assertEqual(operation.await_count, 2)
        sleep.assert_awaited_once_with(0.5)


class ExplorationHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        exploration_handler.ACTIVE_EXPLORATIONS.clear()
        self.report = ExplorationReport(
            space="Пространство.",
            traces="Следы.",
            response="Отклик.",
        )

    def tearDown(self) -> None:
        exploration_handler.ACTIVE_EXPLORATIONS.clear()

    async def test_bad_edit_falls_back_to_new_message(self) -> None:
        replacement = SimpleNamespace()
        source_message = SimpleNamespace(
            answer=AsyncMock(return_value=replacement),
        )
        progress_message = SimpleNamespace(
            edit_text=AsyncMock(
                side_effect=TelegramBadRequest(
                    method=EditMessageText(
                        chat_id=1,
                        message_id=2,
                        text="result",
                    ),
                    message="message cannot be edited",
                )
            )
        )

        result = await exploration_handler._edit_or_answer(
            source_message,
            progress_message,
            "result",
        )

        self.assertIs(result, replacement)
        source_message.answer.assert_awaited_once_with("result")

    async def test_cooldown_is_not_saved_without_final_delivery(self) -> None:
        user_id = 42
        progress_message = SimpleNamespace()
        message = SimpleNamespace(
            text="/исследовать комнату Архив №7",
            from_user=SimpleNamespace(id=user_id),
            answer=AsyncMock(return_value=progress_message),
        )

        with (
            patch.object(exploration_handler, "get_room_exploration_time", return_value=None),
            patch.object(exploration_handler, "get_last_room_exploration_time", return_value=None),
            patch.object(exploration_handler, "choose_exploration_report", return_value=self.report),
            patch.object(exploration_handler, "choose_revisit_note", return_value=None),
            patch.object(
                exploration_handler,
                "_run_exploration_progress",
                new=AsyncMock(return_value=progress_message),
            ),
            patch.object(
                exploration_handler,
                "_edit_or_answer",
                new=AsyncMock(return_value=None),
            ),
            patch.object(exploration_handler, "save_room_exploration") as save_result,
        ):
            await exploration_handler.explore_room(message)

        save_result.assert_not_called()
        self.assertNotIn(user_id, exploration_handler.ACTIVE_EXPLORATIONS)

    async def test_successful_result_saves_full_history(self) -> None:
        user_id = 43
        progress_message = SimpleNamespace()
        message = SimpleNamespace(
            text="/исследовать комнату Архив №7",
            from_user=SimpleNamespace(id=user_id),
            answer=AsyncMock(return_value=progress_message),
        )

        with (
            patch.object(exploration_handler, "get_room_exploration_time", return_value=None),
            patch.object(exploration_handler, "get_last_room_exploration_time", return_value=None),
            patch.object(exploration_handler, "choose_exploration_report", return_value=self.report),
            patch.object(exploration_handler, "choose_revisit_note", return_value=None),
            patch.object(
                exploration_handler,
                "_run_exploration_progress",
                new=AsyncMock(return_value=progress_message),
            ),
            patch.object(
                exploration_handler,
                "_edit_or_answer",
                new=AsyncMock(return_value=progress_message),
            ),
            patch.object(exploration_handler, "save_room_exploration") as save_result,
        ):
            await exploration_handler.explore_room(message)

        save_result.assert_called_once_with(
            user_id=user_id,
            room_key="архив №7",
            room_name="Архив №7",
            space_result="Пространство.",
            traces_result="Следы.",
            response_result="Отклик.",
            revisit_note=None,
        )
        self.assertNotIn(user_id, exploration_handler.ACTIVE_EXPLORATIONS)

    async def test_my_journal_is_plain_text_without_buttons(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=50),
            answer=AsyncMock(),
        )
        entries = [
            {
                "room_name": "Мастерская",
                "exploration_count": 2,
            },
            {
                "room_name": "Холл",
                "exploration_count": 1,
            },
        ]

        with patch.object(
            exploration_handler,
            "get_room_exploration_journal",
            return_value=entries,
        ):
            await exploration_handler.show_my_exploration_journal(message)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        self.assertIn("Мастерская", text)
        self.assertIn("Всего исследований: 3", text)
        self.assertEqual(message.answer.await_args.kwargs, {})


if __name__ == "__main__":
    unittest.main()
