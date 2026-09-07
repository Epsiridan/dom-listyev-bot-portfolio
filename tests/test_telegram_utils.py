import unittest

from services.telegram_utils import callback_int_id, callback_value, split_text_chunks


class TelegramUtilsTests(unittest.TestCase):
    def test_split_text_chunks_keeps_empty_text_as_one_chunk(self) -> None:
        self.assertEqual(split_text_chunks(""), [""])

    def test_split_text_chunks_uses_requested_size(self) -> None:
        self.assertEqual(split_text_chunks("abcdef", chunk_size=2), ["ab", "cd", "ef"])

    def test_split_text_chunks_rejects_invalid_size(self) -> None:
        with self.assertRaises(ValueError):
            split_text_chunks("text", chunk_size=0)

    def test_callback_value_and_int_id(self) -> None:
        self.assertEqual(callback_value("event_view:42"), "42")
        self.assertEqual(callback_int_id("event_view:42"), 42)

    def test_callback_value_rejects_malformed_data(self) -> None:
        for value in (None, "event_view", "event_view:"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                callback_value(value)


if __name__ == "__main__":
    unittest.main()
