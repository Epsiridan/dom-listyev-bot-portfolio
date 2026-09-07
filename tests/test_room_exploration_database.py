import os
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from services import database
from services.database_schema import SCHEMA_STATEMENTS


class RoomExplorationDatabaseTests(unittest.TestCase):
    def test_history_is_saved_and_grouped_for_journal(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)

        @contextmanager
        def shared_connection():
            yield connection

        timestamps = [
            "2026-07-13T10:00:00+03:00",
            "2026-07-13T18:00:00+03:00",
            "2026-07-14T02:00:00+03:00",
        ]
        try:
            with (
                patch.object(database, "_connect", shared_connection),
                patch.object(database, "_now_iso", side_effect=timestamps),
            ):
                database.save_room_exploration(
                    user_id=1,
                    room_key="архив №7",
                    room_name="Архив №7",
                    space_result="space-1",
                    traces_result="traces-1",
                    response_result="response-1",
                    revisit_note=None,
                )
                database.save_room_exploration(
                    user_id=1,
                    room_key="архив №7",
                    room_name="архив №7",
                    space_result="space-2",
                    traces_result="traces-2",
                    response_result="response-2",
                    revisit_note="note",
                )
                database.save_room_exploration(
                    user_id=1,
                    room_key="special:hall",
                    room_name="Холл",
                    space_result="space-3",
                    traces_result="traces-3",
                    response_result="response-3",
                    revisit_note=None,
                )

                journal = database.get_room_exploration_journal(1)
                last_visit = database.get_last_room_exploration_time(
                    1,
                    "архив №7",
                )
                cooldown = database.get_room_exploration_time(1)

            self.assertEqual(len(journal), 2)
            self.assertEqual(journal[0]["room_name"], "Холл")
            archive = next(row for row in journal if row["room_key"] == "архив №7")
            self.assertEqual(archive["exploration_count"], 2)
            self.assertEqual(archive["room_name"], "архив №7")
            self.assertEqual(last_visit, timestamps[1])
            self.assertEqual(cooldown, timestamps[2])
            history_count = connection.execute(
                "SELECT COUNT(*) FROM room_exploration_history"
            ).fetchone()[0]
            self.assertEqual(history_count, 3)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
