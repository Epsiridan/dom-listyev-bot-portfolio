import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from services.publications import (
    send_rejected_post_to_archive,
    send_review_card,
    send_stored_review_card,
)


def _submission_data(text: str) -> dict:
    return {
        "source_link": None,
        "author_label": "Имя / @username / ID: 123456789",
        "publish_author": True,
        "creative_group": None,
        "creative_group_format": "plain",
        "media_type": None,
        "text_format": "plain",
        "text": text,
    }


def _sent_message(message_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(id=-1004),
        message_id=message_id,
        message_thread_id=7,
    )


def _stored_post(text: str) -> dict:
    return {
        "id": 42,
        "source_link": None,
        "user_id": 123456789,
        "username": "username",
        "full_name": "Имя",
        "publish_author": 1,
        "creative_group": None,
        "creative_group_format": "plain",
        "media_type": None,
        "text_format": "plain",
        "text": text,
    }


class ProposedPostReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_review_keeps_text_and_controls_together(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock(return_value=_sent_message(10)))

        sent = await send_review_card(bot, post_id=42, data=_submission_data("Короткий текст"))

        self.assertEqual(sent.message_id, 10)
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertIn("Короткий текст", kwargs["text"])
        self.assertIsNotNone(kwargs["reply_markup"])

    async def test_long_review_sends_controls_and_body_separately(self) -> None:
        long_text = "я" * 4000
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=[_sent_message(20), _sent_message(21)])
        )

        sent = await send_review_card(bot, post_id=42, data=_submission_data(long_text))

        self.assertEqual(sent.message_id, 20)
        self.assertEqual(bot.send_message.await_count, 2)
        summary_call, body_call = bot.send_message.await_args_list
        self.assertNotIn(long_text, summary_call.kwargs["text"])
        self.assertIn("следующим сообщением", summary_call.kwargs["text"])
        self.assertIsNotNone(summary_call.kwargs["reply_markup"])
        self.assertEqual(body_call.kwargs["text"], long_text)
        self.assertNotIn("reply_markup", body_call.kwargs)

    async def test_long_stored_review_is_safe_after_admin_edit(self) -> None:
        long_text = "я" * 4000
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=[_sent_message(30), _sent_message(31)])
        )

        sent = await send_stored_review_card(
            bot,
            chat_id=-1009,
            message_thread_id=77,
            post=_stored_post(long_text),
        )

        self.assertEqual(sent.message_id, 30)
        self.assertEqual(bot.send_message.await_count, 2)
        summary_call, body_call = bot.send_message.await_args_list
        self.assertEqual(summary_call.kwargs["chat_id"], -1009)
        self.assertEqual(summary_call.kwargs["message_thread_id"], 77)
        self.assertIsNotNone(summary_call.kwargs["reply_markup"])
        self.assertEqual(body_call.kwargs["text"], long_text)
        self.assertEqual(body_call.kwargs["message_thread_id"], 77)

    async def test_long_rejected_post_is_archived_in_two_messages(self) -> None:
        long_text = "я" * 4000
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=[_sent_message(40), _sent_message(41)])
        )

        await send_rejected_post_to_archive(bot, _stored_post(long_text))

        self.assertEqual(bot.send_message.await_count, 2)
        summary_call, body_call = bot.send_message.await_args_list
        self.assertIn("следующим сообщением", summary_call.kwargs["text"])
        self.assertEqual(body_call.kwargs["text"], long_text)


if __name__ == "__main__":
    unittest.main()
