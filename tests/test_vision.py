import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from handlers.vision import (
    _handle_vision_request,
    extract_user_request,
    find_request_image,
    image_from_message,
)
from config import settings
from services.vision import build_vision_request, describe_image, safety_identifier


def make_message(**overrides):
    values = {
        "text": None,
        "caption": None,
        "photo": None,
        "document": None,
        "reply_to_message": None,
        "from_user": SimpleNamespace(id=42, is_bot=False),
        "chat": SimpleNamespace(id=-2001, type="supergroup"),
        "answer": AsyncMock(),
        "reply": AsyncMock(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeResponses:
    def __init__(self, output_text: str = "Описание") -> None:
        self.output_text = output_text
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


class FakeOpenAIClient:
    def __init__(self, output_text: str = "Описание") -> None:
        self.responses = FakeResponses(output_text)


class VisionParsingTests(unittest.TestCase):
    def test_extracts_optional_request_from_text_or_caption(self) -> None:
        text_message = make_message(
            text="/опознай@DomListyevBot прочитай мелкий текст"
        )
        caption_message = make_message(caption="/ОПОЗНАЙ@domlistyevbot")

        self.assertEqual(
            extract_user_request(text_message),
            "прочитай мелкий текст",
        )
        self.assertIsNone(extract_user_request(caption_message))

    def test_selects_direct_photo_before_replied_photo(self) -> None:
        replied = make_message(photo=[SimpleNamespace(file_id="reply-photo")])
        direct = make_message(
            photo=[
                SimpleNamespace(file_id="small"),
                SimpleNamespace(file_id="large"),
            ],
            reply_to_message=replied,
        )

        selected = find_request_image(direct)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.file_id, "large")
        self.assertEqual(selected.mime_type, "image/jpeg")
        self.assertIs(selected.source_message, direct)

    def test_selects_replied_image_document_by_extension(self) -> None:
        replied = make_message(
            document=SimpleNamespace(
                file_id="png-document",
                mime_type=None,
                file_name="picture.png",
            )
        )
        command = make_message(reply_to_message=replied)

        selected = find_request_image(command)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.file_id, "png-document")
        self.assertEqual(selected.mime_type, "image/png")

    def test_rejects_non_image_document(self) -> None:
        message = make_message(
            document=SimpleNamespace(
                file_id="pdf-document",
                mime_type="application/pdf",
                file_name="document.pdf",
            )
        )

        self.assertIsNone(image_from_message(message))


class VisionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_multimodal_response_without_real_api_call(self) -> None:
        client = FakeOpenAIClient("  На фото кот.  ")

        result = await describe_image(
            b"image-bytes",
            mime_type="image/png",
            user_id=42,
            user_request="прочитай подпись",
            client=client,
        )

        self.assertEqual(result, "На фото кот.")
        request = client.responses.kwargs
        self.assertEqual(request["model"], settings.OPENAI_VISION_MODEL)
        self.assertEqual(request["reasoning"], {"effort": "low"})
        self.assertFalse(request["store"])
        self.assertEqual(request["input"][0]["content"][1]["detail"], "original")
        self.assertTrue(
            request["input"][0]["content"][1]["image_url"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertIn("прочитай подпись", request["input"][0]["content"][0]["text"])
        self.assertEqual(request["safety_identifier"], safety_identifier(42))

    def test_default_request_keeps_accessible_description_as_goal(self) -> None:
        self.assertIn("полное", build_vision_request(None))
        self.assertIn("доступное описание", build_vision_request("цвета"))


class VisionAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_denies_non_member_before_downloading_image(self) -> None:
        message = make_message(text="/опознай@DomListyevBot")
        bot = SimpleNamespace()

        with (
            patch("handlers.vision.user_is_member", AsyncMock(return_value=False)),
            patch("handlers.vision.download_image", AsyncMock()) as download,
        ):
            await _handle_vision_request(message, bot)

        download.assert_not_awaited()
        message.answer.assert_awaited_once()
        self.assertIn("только участникам", message.answer.await_args.args[0])

    async def test_describes_direct_image_for_member(self) -> None:
        message = make_message(
            caption="/опознай@DomListyevBot",
            photo=[SimpleNamespace(file_id="photo-id")],
        )
        bot = SimpleNamespace()

        with (
            patch("handlers.vision.user_is_member", AsyncMock(return_value=True)),
            patch("handlers.vision.download_image", AsyncMock(return_value=b"image")),
            patch(
                "handlers.vision.describe_image",
                AsyncMock(return_value="Доступное описание"),
            ) as describe,
            patch("handlers.vision.reply_with_chunks", AsyncMock()) as reply,
        ):
            await _handle_vision_request(message, bot)

        describe.assert_awaited_once_with(
            b"image",
            mime_type="image/jpeg",
            user_id=42,
            user_request=None,
        )
        reply.assert_awaited_once_with(message, "Доступное описание")


if __name__ == "__main__":
    unittest.main()
