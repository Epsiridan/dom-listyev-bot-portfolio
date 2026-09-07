# -*- coding: utf-8 -*-

import os
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from services import database
from config import settings
from services.events import event_registration_is_open, should_send_link_after_registration
from services.database_schema import SCHEMA_STATEMENTS


class HouseEventDeletionTests(unittest.TestCase):
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

    def test_delete_event_removes_registrations_and_list_entry(self) -> None:
        event_id = database.create_house_event(
            title="Тест",
            description="Удалить после прогона",
            event_at="2099-01-31T18:00:00+03:00",
            reminder_at=None,
            broadcast_text="Напоминание",
            link=None,
            created_by=1,
        )
        self.assertTrue(
            database.register_for_house_event(
                event_id=event_id,
                user_id=42,
                username="reader",
                full_name="Reader",
            )
        )

        self.assertTrue(database.delete_house_event(event_id))
        self.assertIsNone(database.get_house_event(event_id))
        self.assertEqual(database.get_house_event_registrations(event_id), [])
        self.assertEqual(database.get_active_house_events(), [])
        self.assertFalse(database.delete_house_event(event_id))

    def _create_event_at(self, event_at: datetime, *, remind_15_min: bool = False) -> int:
        return database.create_house_event(
            title="Окно записи",
            description="Тест временной логики",
            event_at=event_at.isoformat(timespec="seconds"),
            reminder_at=(event_at - timedelta(hours=2)).isoformat(timespec="seconds"),
            broadcast_text="Напоминание {link}",
            link="https://example.com/meeting",
            created_by=1,
            remind_15_min=remind_15_min,
        )

    def test_registration_stays_open_for_first_30_minutes(self) -> None:
        event_at = datetime.now(settings.MOSCOW_TZ) - timedelta(minutes=20)
        event_id = self._create_event_at(event_at)

        self.assertTrue(
            database.register_for_house_event(
                event_id=event_id,
                user_id=7,
                username=None,
                full_name="Late Reader",
            )
        )
        self.assertEqual([row["id"] for row in database.get_active_house_events()], [event_id])
        self.assertEqual(database.get_public_archived_house_events(), [])

    def test_registration_closes_and_event_is_archived_after_30_minutes(self) -> None:
        event_at = datetime.now(settings.MOSCOW_TZ) - timedelta(minutes=31)
        event_id = self._create_event_at(event_at)

        self.assertFalse(
            database.register_for_house_event(
                event_id=event_id,
                user_id=8,
                username=None,
                full_name="Too Late Reader",
            )
        )
        self.assertEqual(database.get_active_house_events(), [])
        self.assertEqual(
            [row["id"] for row in database.get_public_archived_house_events()],
            [event_id],
        )

    def test_optional_15_minute_reminder_becomes_due(self) -> None:
        event_id = self._create_event_at(
            datetime.now(settings.MOSCOW_TZ) + timedelta(minutes=10),
            remind_15_min=True,
        )

        self.assertEqual(
            [row["id"] for row in database.get_due_house_event_15_min_reminders()],
            [event_id],
        )
        database.mark_house_event_reminder_sent(event_id, fifteen_minute=True)
        self.assertEqual(database.get_due_house_event_15_min_reminders(), [])

    def test_late_registration_requires_immediate_link(self) -> None:
        now = datetime.now(settings.MOSCOW_TZ)
        event_id = self._create_event_at(now + timedelta(minutes=10))
        event = database.get_house_event(event_id)

        self.assertTrue(should_send_link_after_registration(event, now=now))
        self.assertTrue(event_registration_is_open(event, now=now + timedelta(minutes=39)))
        self.assertFalse(event_registration_is_open(event, now=now + timedelta(minutes=41)))


if __name__ == "__main__":
    unittest.main()
