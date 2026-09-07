import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from config import settings
from handlers import content_admin
from keyboards_parts.contest import contest_preview_keyboard
from services import database
from services.content import ContentBlock, get_content_block, reset_block, save_block, send_content
from states import ContentAdmin


class FakeState:
    def __init__(self, data): self.data=dict(data); self.state=None; self.cleared=False
    async def get_data(self): return dict(self.data)
    async def update_data(self, **kwargs): self.data.update(kwargs)
    async def set_state(self, state): self.state=state
    async def clear(self): self.cleared=True; self.data.clear()


class FakeMessage:
    def __init__(self, text=None, photo=None):
        self.text=text; self.caption=None; self.photo=photo; self.from_user=type("User",(),{"id":777})()
        self.answer=AsyncMock(return_value="text-message")
        self.answer_photo=AsyncMock(return_value="photo-message")


class FakeCallback:
    def __init__(self, data, message=None):
        self.data=data; self.message=message or FakeMessage(); self.from_user=type("User",(),{"id":777})()
        self.answer=AsyncMock()


class ContentStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.old_dir=settings.DATA_DIR; self.old_path=settings.DB_PATH
        object.__setattr__(settings,"DATA_DIR",__import__("pathlib").Path(self.temp.name))
        object.__setattr__(settings,"DB_PATH",__import__("pathlib").Path(self.temp.name)/"content.db")
        database.init_db()

    def tearDown(self):
        object.__setattr__(settings,"DATA_DIR",self.old_dir); object.__setattr__(settings,"DB_PATH",self.old_path)
        self.temp.cleanup()

    def test_fallback_override_and_reset(self):
        default=get_content_block("main_menu")
        self.assertFalse(default.is_custom)
        custom=ContentBlock("main_menu",default.title,"Новый текст",None,"auto",True)
        save_block(custom,updated_by=777)
        self.assertEqual(get_content_block("main_menu").text,"Новый текст")
        reset_block("main_menu")
        self.assertEqual(get_content_block("main_menu").text,default.text)

    def test_add_replace_and_remove_image(self):
        block=get_content_block("main_menu")
        save_block(ContentBlock(block.key,block.title,block.text,"file-one","auto",True),updated_by=1)
        self.assertEqual(get_content_block(block.key).image_file_id,"file-one")
        save_block(ContentBlock(block.key,block.title,block.text,"file-two","caption",True),updated_by=2)
        self.assertEqual(get_content_block(block.key).image_file_id,"file-two")
        save_block(ContentBlock(block.key,block.title,block.text,None,"text",True),updated_by=3)
        self.assertIsNone(get_content_block(block.key).image_file_id)

    async def test_send_modes_caption_and_separate(self):
        block=get_content_block("main_menu")
        save_block(ContentBlock(block.key,block.title,"Коротко","photo-id","caption",True),updated_by=1)
        message=FakeMessage(); await send_content(message,block.key)
        message.answer_photo.assert_awaited_once()
        self.assertEqual(message.answer_photo.await_args.kwargs["caption"],"Коротко")
        save_block(ContentBlock(block.key,block.title,"Длинный текст","photo-id","separate",True),updated_by=1)
        message=FakeMessage(); await send_content(message,block.key)
        message.answer_photo.assert_awaited_once_with("photo-id")
        message.answer.assert_awaited()

    async def test_cancel_clears_fsm_and_does_not_change_database(self):
        original=get_content_block("main_menu").text
        state=FakeState({"content_key":"main_menu","pending_value":"Не сохранять"})
        callback=FakeCallback("content_cancel:main_menu")
        with patch.object(content_admin,"_allowed",AsyncMock(return_value=True)), patch.object(content_admin,"_show_detail",AsyncMock()):
            await content_admin.content_cancel(callback,state)
        self.assertTrue(state.cleared)
        self.assertEqual(get_content_block("main_menu").text,original)

    async def test_comparison_contains_before_and_after(self):
        old=get_content_block("main_menu").text
        state=FakeState({"content_key":"main_menu","edit_kind":"text"})
        message=FakeMessage(text="Новое значение")
        with patch.object(content_admin,"is_admin",return_value=True):
            await content_admin.content_text_received(message,state)
        shown=message.answer.await_args.args[0]
        self.assertIn("Было:",shown); self.assertIn("Станет:",shown)
        self.assertIn("Новое значение",shown); self.assertIn(old[:20],shown)
        self.assertEqual(state.state,ContentAdmin.confirming)

    def test_contest_creation_preview_has_no_cancel_button(self):
        labels=[button.text for row in contest_preview_keyboard.inline_keyboard for button in row]
        self.assertFalse(any("Отмен" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
