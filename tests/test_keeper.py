import asyncio
import os
import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from services import database
from services.database_schema import SCHEMA_STATEMENTS
from services.keeper import (
    KEEPER_FINAL_REPLY,
    KEEPER_MAX_REPLIES,
    keeper_opening,
    keeper_reply,
    wants_to_end,
)
from handlers import keeper as keeper_handler


class KeeperSpeechTests(unittest.TestCase):
    def test_opening_names_room_and_invites_conversation(self) -> None:
        text = keeper_opening("Зал")

        self.assertIn("«Зал»", text)
        self.assertIn("Побудьте здесь", text)

    def test_tenth_reply_is_strict_closing(self) -> None:
        text = keeper_reply(
            "Расскажи ещё",
            reply_number=KEEPER_MAX_REPLIES,
            room_name="Зал",
        )

        self.assertEqual(text, KEEPER_FINAL_REPLY)
        self.assertIn("продолжать обход", text)
        self.assertIn("разговор окончен", text)

    def test_explicit_stop_closes_early(self) -> None:
        self.assertTrue(wants_to_end("Ладно, давай закончим."))
        self.assertEqual(
            keeper_reply("Стоп", reply_number=3, room_name="Зал"),
            KEEPER_FINAL_REPLY,
        )

    def test_search_answer_matches_tested_tone(self) -> None:
        text = keeper_reply("Найти", reply_number=2, room_name="Зал")

        self.assertIn("Так обычно и говорят", text)
        self.assertIn("для своего искусства", text)

    def test_known_event_is_recalled_without_inventing_details(self) -> None:
        text = keeper_reply(
            "Помнишь ЭХО?",
            reply_number=4,
            room_name="Зал",
            memory_record={
                "record_kind": "contest",
                "title": "ЭХО // мерцание",
                "happened_at": "2026-07-31T21:00:00+03:00",
                "status": "finished",
            },
        )

        self.assertIn("«ЭХО // мерцание»", text)
        self.assertIn("завершена", text)


class KeeperDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for statement in SCHEMA_STATEMENTS:
            self.connection.execute(statement)

        @contextmanager
        def shared_connection():
            yield self.connection

        self.connection_patch = patch.object(database, "_connect", shared_connection)
        self.connection_patch.start()

    def tearDown(self) -> None:
        self.connection_patch.stop()
        self.connection.close()

    def test_easter_egg_can_only_be_claimed_once(self) -> None:
        with patch.object(database, "_now_iso", return_value="2026-09-04T10:00:00+03:00"):
            database.arm_keeper_easter_egg(armed_by=1)
            first = database.claim_keeper_easter_egg(claimed_by=2)
            second = database.claim_keeper_easter_egg(claimed_by=3)

        self.assertTrue(first)
        self.assertFalse(second)

    def test_dialogue_starts_with_opening_counted_as_first_reply(self) -> None:
        with patch.object(database, "_now_iso", return_value="2026-09-04T10:00:00+03:00"):
            dialogue_id = database.start_keeper_dialogue(
                chat_id=-1001,
                message_thread_id=7,
                trigger_user_id=2,
                room_name="Зал",
                last_bot_message_id=50,
            )

        row = self.connection.execute(
            "SELECT * FROM keeper_dialogues WHERE id = ?", (dialogue_id,)
        ).fetchone()
        self.assertEqual(row["reply_count"], 1)
        self.assertEqual(row["status"], "active")

    def test_named_house_record_can_be_found_locally(self) -> None:
        self.connection.execute(
            """
            INSERT INTO house_events (
                title, description, event_at, reminder_at, broadcast_text, link,
                status, created_by, created_at, updated_at, remind_15_min
            ) VALUES (?, '', ?, NULL, '', NULL, 'finished', 1, ?, ?, 0)
            """,
            (
                "Вечер белого пера",
                "2026-08-01T19:00:00+03:00",
                "2026-07-01T10:00:00+03:00",
                "2026-08-01T20:00:00+03:00",
            ),
        )

        row = database.find_keeper_record("А что было на вечере белого пера?")

        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Вечер белого пера")

    def test_due_dialogue_is_claimed_and_closed_with_one_final_reply(self) -> None:
        with patch.object(database, "_now_iso", return_value="2020-01-01T10:00:00+03:00"):
            dialogue_id = database.start_keeper_dialogue(
                chat_id=-1001,
                message_thread_id=None,
                trigger_user_id=2,
                room_name="Зал",
                last_bot_message_id=50,
            )

        due = database.claim_due_keeper_dialogue()
        self.assertIsNotNone(due)
        self.assertEqual(due["id"], dialogue_id)

        database.complete_due_keeper_dialogue(dialogue_id)
        row = self.connection.execute(
            "SELECT * FROM keeper_dialogues WHERE id = ?", (dialogue_id,)
        ).fetchone()
        self.assertEqual(row["status"], "finished")
        self.assertEqual(row["reply_count"], 2)


class KeeperTimeoutLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_loop_sends_strict_closing_to_original_topic(self) -> None:
        due = {
            "id": 8,
            "chat_id": -1001,
            "message_thread_id": 77,
        }
        bot = SimpleNamespace(send_message=AsyncMock())

        with (
            patch.object(
                keeper_handler,
                "claim_due_keeper_dialogue",
                side_effect=[due, None],
            ),
            patch.object(keeper_handler, "complete_due_keeper_dialogue") as complete,
            patch.object(
                keeper_handler.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await keeper_handler.keeper_dialogue_timeout_loop(bot)

        bot.send_message.assert_awaited_once_with(
            chat_id=-1001,
            text=KEEPER_FINAL_REPLY,
            message_thread_id=77,
        )
        complete.assert_called_once_with(8)


if __name__ == "__main__":
    unittest.main()
