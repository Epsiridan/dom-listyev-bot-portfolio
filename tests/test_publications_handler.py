import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from handlers.publications import (
    AUTHOR_VISIBILITY_NO_VALUES,
    AUTHOR_VISIBILITY_YES_VALUES,
    _finish_author_visibility_choice,
)
from keyboards import restart_keyboard


class ProposedPostCompletionTests(unittest.IsolatedAsyncioTestCase):
    def test_full_button_labels_are_valid_text_fallbacks(self) -> None:
        self.assertIn("да, указать автора", AUTHOR_VISIBILITY_YES_VALUES)
        self.assertIn("нет, опубликовать анонимно", AUTHOR_VISIBILITY_NO_VALUES)

    async def _finish(self, *, group_submission: bool):
        message = object()
        state = AsyncMock()
        state.get_data.return_value = {
            "cleanup_group_bot_messages": group_submission,
        }
        bot = object()

        with (
            patch(
                "handlers.publications._finish_proposed_post_submission",
                new=AsyncMock(return_value=(42, [])),
            ),
            patch(
                "handlers.publications._delete_remembered_cleanup_messages",
                new=AsyncMock(),
            ),
            patch(
                "handlers.publications.send_content",
                new=AsyncMock(),
            ) as send_content_mock,
        ):
            await _finish_author_visibility_choice(
                message,
                state,
                bot,
                publish_author=True,
            )

        return send_content_mock

    async def test_group_submission_has_no_final_keyboard(self) -> None:
        send_content_mock = await self._finish(group_submission=True)

        self.assertIsNone(send_content_mock.await_args.kwargs["reply_markup"])

    async def test_private_submission_keeps_home_keyboard(self) -> None:
        send_content_mock = await self._finish(group_submission=False)

        self.assertIs(
            send_content_mock.await_args.kwargs["reply_markup"],
            restart_keyboard,
        )


if __name__ == "__main__":
    unittest.main()
