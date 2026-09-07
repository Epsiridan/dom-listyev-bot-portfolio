import os
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from services import database


class DatabaseConnectionTests(unittest.TestCase):
    def test_connect_context_closes_connection(self) -> None:
        with patch.object(database, "settings", replace(database.settings, DB_PATH=Path(":memory:"))):
            with database._connect() as connection:
                connection.execute("CREATE TABLE sample (id INTEGER)")

            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
