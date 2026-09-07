import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from config import _get_bounded_int_env, _get_int_set_env, load_settings


class ConfigParsingTests(unittest.TestCase):
    def test_bounded_int_accepts_valid_value(self) -> None:
        with patch.dict(os.environ, {"TEST_BOUNDED_INT": "23"}):
            self.assertEqual(
                _get_bounded_int_env(
                    "TEST_BOUNDED_INT",
                    0,
                    minimum=0,
                    maximum=23,
                ),
                23,
            )

    def test_bounded_int_rejects_out_of_range_value(self) -> None:
        with patch.dict(os.environ, {"TEST_BOUNDED_INT": "24"}):
            with self.assertRaisesRegex(RuntimeError, "TEST_BOUNDED_INT"):
                _get_bounded_int_env(
                    "TEST_BOUNDED_INT",
                    0,
                    minimum=0,
                    maximum=23,
                )

    def test_admin_ids_are_immutable_and_deduplicated(self) -> None:
        with patch.dict(os.environ, {"TEST_ADMIN_IDS": "1, 2, 1"}):
            values = _get_int_set_env("TEST_ADMIN_IDS")

        self.assertEqual(values, frozenset({1, 2}))
        self.assertIsInstance(values, frozenset)

    def test_env_has_priority_over_config_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                "general_group_id: -2001\n"
                "public_channel_id: -2002\n"
                "partner_channel_id: -2003\n"
                "admin_ids: [10, 20]\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "BOT_TOKEN": "123456:TESTTOKEN",
                    "GENERAL_GROUP_ID": "-9001",
                    "ADMIN_GROUP_ID": "-9004",
                    "ADMIN_IDS": "30",
                },
                clear=True,
            ):
                loaded = load_settings(path)

        self.assertEqual(loaded.GENERAL_GROUP_ID, -9001)
        self.assertEqual(loaded.PUBLIC_CHANNEL_ID, -2002)
        self.assertEqual(loaded.ADMIN_IDS, frozenset({30}))

if __name__ == "__main__":
    unittest.main()
