# -*- coding: utf-8 -*-

import os
import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from aiogram.enums import ChatMemberStatus

from services import contest_database, contests
from services.contests import (
    default_success_message,
    message_matches_allowed_file,
    parse_topic_message_link,
    validate_required_channels,
)
from services.database_schema import SCHEMA_STATEMENTS


class ContestServiceTests(unittest.TestCase):
    def test_topic_link_parses_public_and_private_forum_links(self) -> None:
        self.assertEqual(
            parse_topic_message_link(
                "https://t.me/dom_listyev_admin/77/120",
                destination_chat_id=-100123,
                destination_username="dom_listyev_admin",
            ),
            77,
        )
        self.assertEqual(
            parse_topic_message_link(
                "https://t.me/c/123456/88/150",
                destination_chat_id=-100123456,
                destination_username=None,
            ),
            88,
        )

    def test_topic_link_rejects_another_group(self) -> None:
        with self.assertRaisesRegex(ValueError, "другую группу"):
            parse_topic_message_link(
                "https://t.me/c/999/88/150",
                destination_chat_id=-100123456,
                destination_username=None,
            )

    def test_file_check_uses_admin_selected_categories(self) -> None:
        docx = SimpleNamespace(
            photo=None,
            audio=None,
            video=None,
            document=SimpleNamespace(file_name="story.DOCX"),
        )
        pdf = SimpleNamespace(
            photo=None,
            audio=None,
            video=None,
            document=SimpleNamespace(file_name="story.pdf"),
        )
        photo = SimpleNamespace(photo=[object()], audio=None, video=None, document=None)
        self.assertTrue(message_matches_allowed_file(docx, ["docx"]))
        self.assertFalse(message_matches_allowed_file(pdf, ["docx"]))
        self.assertTrue(message_matches_allowed_file(photo, ["images"]))

    def test_default_success_message_escapes_title(self) -> None:
        text = default_success_message("A < B")
        self.assertIn("A &lt; B", text)
        self.assertNotIn("A < B", text)

    def test_deleted_seeded_contest_is_not_recreated(self) -> None:
        with (
            patch.object(contests, "get_contest_by_external_key", return_value=None),
            patch.object(contests, "contest_external_key_was_deleted", return_value=True),
            patch.object(contests, "create_contest") as create_contest_mock,
        ):
            self.assertIsNone(contests.ensure_echo_contest())
        create_contest_mock.assert_not_called()


class FakeChannelBot:
    async def get_me(self):
        return SimpleNamespace(id=10)

    async def get_chat(self, reference):
        username = reference.lstrip("@")
        return SimpleNamespace(
            id={"first_channel": -1001, "second_channel": -1002}[username],
            title=username,
            username=username,
        )

    async def get_chat_member(self, chat_id, user_id):
        status = ChatMemberStatus.ADMINISTRATOR if chat_id == -1001 else ChatMemberStatus.MEMBER
        return SimpleNamespace(status=status)


class ContestChannelValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_channel_requires_bot_admin_status(self) -> None:
        channels, errors = await validate_required_channels(
            FakeChannelBot(),
            "https://t.me/first_channel https://t.me/second_channel",
        )
        self.assertEqual([item["channel_id"] for item in channels], [-1001])
        self.assertEqual(len(errors), 1)
        self.assertIn("не администратор", errors[0])


class ContestDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for statement in SCHEMA_STATEMENTS:
            self.connection.execute(statement)

        @contextmanager
        def shared_connection():
            yield self.connection

        self.connection_patch = patch.object(contest_database, "_connect", shared_connection)
        self.connection_patch.start()

    def tearDown(self) -> None:
        self.connection_patch.stop()
        self.connection.close()

    def test_create_finish_and_count_submissions(self) -> None:
        contest_id = contest_database.create_contest(
            {
                "title": "Тест",
                "button_text": "🎨 Тест",
                "description_html": "<i>Текст</i>",
                "criteria_html": "Критерии",
                "show_community_rules": True,
                "starts_at": "2099-01-01T10:00:00+03:00",
                "ends_at": "2099-01-31T21:00:00+03:00",
                "require_repost": False,
                "ask_ai": False,
                "submission_mode": "files",
                "allowed_file_categories": ["pdf"],
                "max_submissions": 2,
                "success_message_html": "Готово",
                "destination_chat_id": -1005,
                "destination_chat_title": "Жюри",
                "destination_thread_id": 7,
                "created_by": 1,
                "required_channels": [
                    {
                        "channel_id": -1009,
                        "title": "Канал",
                        "username": "channel_name",
                        "url": "https://t.me/channel_name",
                    }
                ],
            }
        )
        contest_database.save_contest_submission(
            contest_id=contest_id,
            user_id=42,
            username="writer",
            full_name="Writer",
            author="Writer",
            title="Work",
            repost_link=None,
            ai_link=None,
            submission_format="file",
        )
        self.assertEqual(contest_database.count_contest_submissions(contest_id), 1)
        self.assertEqual(contest_database.count_user_contest_submissions(contest_id, 42), 1)
        self.assertEqual(len(contest_database.get_contest_channels(contest_id)), 1)
        self.assertEqual([row["id"] for row in contest_database.get_visible_contests()], [contest_id])
        self.assertTrue(contest_database.finish_contest(contest_id))
        self.assertEqual(contest_database.get_contest(contest_id)["status"], "finished")
        self.assertEqual(contest_database.get_visible_contests(), [])

    def test_legacy_submission_migration_is_idempotent(self) -> None:
        self.connection.execute(
            """
            INSERT INTO submissions (user_id, username, full_name, title, submitted_at)
            VALUES (42, 'writer', 'Writer', 'Old work', '2026-07-01T18:00:00+03:00')
            """
        )
        contest_id = contest_database.create_contest(
            {
                "title": "ЭХО",
                "button_text": "🎨 ЭХО",
                "description_html": "Текст",
                "criteria_html": "",
                "show_community_rules": False,
                "starts_at": "2026-07-01T18:00:00+03:00",
                "ends_at": "2026-07-31T21:00:00+03:00",
                "require_repost": True,
                "ask_ai": True,
                "submission_mode": "both",
                "allowed_file_categories": ["txt", "docx"],
                "max_submissions": 1,
                "success_message_html": "Готово",
                "destination_chat_id": -1005,
                "destination_chat_title": "Жюри",
                "destination_thread_id": None,
                "created_by": 0,
                "required_channels": [],
            }
        )
        self.assertEqual(contest_database.migrate_legacy_submissions(contest_id), 1)
        self.assertEqual(contest_database.migrate_legacy_submissions(contest_id), 0)
        self.assertEqual(contest_database.count_contest_submissions(contest_id), 1)

    def test_delete_contest_removes_channels_submissions_and_buttons_source(self) -> None:
        contest_id = contest_database.create_contest(
            {
                "external_key": "test_seeded_contest",
                "title": "Удалить",
                "button_text": "🎨 Удалить",
                "description_html": "Тест",
                "criteria_html": "",
                "show_community_rules": False,
                "starts_at": "2099-01-01T10:00:00+03:00",
                "ends_at": "2099-01-31T21:00:00+03:00",
                "require_repost": False,
                "ask_ai": False,
                "submission_mode": "text",
                "allowed_file_categories": [],
                "max_submissions": 1,
                "success_message_html": "Готово",
                "destination_chat_id": -1005,
                "destination_chat_title": "Жюри",
                "destination_thread_id": None,
                "created_by": 1,
                "required_channels": [
                    {
                        "channel_id": -1009,
                        "title": "Канал",
                        "username": "channel_name",
                        "url": "https://t.me/channel_name",
                    }
                ],
            }
        )
        contest_database.save_contest_submission(
            contest_id=contest_id,
            user_id=42,
            username="writer",
            full_name="Writer",
            author="Writer",
            title="Work",
            repost_link=None,
            ai_link=None,
            submission_format="text",
        )

        self.assertTrue(contest_database.delete_contest(contest_id))
        self.assertIsNone(contest_database.get_contest(contest_id))
        self.assertEqual(contest_database.get_contest_channels(contest_id), [])
        self.assertEqual(contest_database.count_contest_submissions(contest_id), 0)
        self.assertEqual(contest_database.get_visible_contests(), [])
        self.assertTrue(contest_database.contest_external_key_was_deleted("test_seeded_contest"))
        self.assertFalse(contest_database.delete_contest(contest_id))


if __name__ == "__main__":
    unittest.main()
