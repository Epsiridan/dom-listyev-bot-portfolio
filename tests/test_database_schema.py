import sqlite3
from contextlib import closing
import unittest

from services.database_schema import (
    HOUSE_EVENT_COMPAT_COLUMNS,
    PROPOSED_POST_COMPAT_COLUMNS,
    SCHEMA_STATEMENTS,
)


class DatabaseSchemaTests(unittest.TestCase):
    def test_schema_creates_all_runtime_tables(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)

            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertTrue(
            {
                "submissions",
                "room_explorations",
                "room_exploration_history",
                "proposed_posts",
                "maintenance_tasks",
                "house_events",
                "house_event_registrations",
                "contests",
                "contest_required_channels",
                "contest_submissions",
                "keeper_easter_egg",
                "keeper_group_messages",
                "keeper_dialogues",
            }.issubset(tables)
        )

    def test_compatibility_columns_have_safe_defaults_or_are_nullable(self) -> None:
        self.assertIn("publish_author", PROPOSED_POST_COMPAT_COLUMNS)
        self.assertIn("DEFAULT", PROPOSED_POST_COMPAT_COLUMNS["publish_author"])
        self.assertNotIn("NOT NULL", PROPOSED_POST_COMPAT_COLUMNS["creative_group"])
        self.assertIn("DEFAULT", HOUSE_EVENT_COMPAT_COLUMNS["remind_15_min"])
        self.assertNotIn("NOT NULL", HOUSE_EVENT_COMPAT_COLUMNS["reminder_15_sent_at"])


if __name__ == "__main__":
    unittest.main()
