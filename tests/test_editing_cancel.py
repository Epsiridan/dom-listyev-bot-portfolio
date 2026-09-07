import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GENERAL_GROUP_ID", "-1001")
os.environ.setdefault("ADMIN_GROUP_ID", "-1004")
os.environ.setdefault("PUBLIC_CHANNEL_ID", "-1002")
os.environ.setdefault("PARTNER_CHANNEL_ID", "-1003")

from handlers import events, publications


class State:
    def __init__(self): self.cleared=False
    async def clear(self): self.cleared=True


class Callback:
    def __init__(self,data):
        self.data=data; self.message=object(); self.from_user=type("User",(),{"id":1})()
        self.answer=AsyncMock()


class ExistingEditCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_cancel_does_not_call_database_update(self):
        callback=Callback("event_edit_cancel:42"); state=State()
        with patch.object(events,"_require_private_admin",AsyncMock(return_value=True)), \
             patch.object(events,"_send_admin_event_detail",AsyncMock()), \
             patch.object(events,"update_house_event_link") as link_update, \
             patch.object(events,"update_house_event_broadcast_text") as text_update:
            await events.event_edit_cancel(callback,state)
        self.assertTrue(state.cleared); link_update.assert_not_called(); text_update.assert_not_called()

    async def test_proposed_post_cancel_does_not_call_database_update(self):
        callback=Callback("proposed_edit_cancel:17"); state=State()
        with patch.object(publications,"is_admin",return_value=True), \
             patch.object(publications,"_return_to_proposed_card",AsyncMock()), \
             patch.object(publications,"update_proposed_post_text") as update:
            await publications.proposed_edit_cancel(callback,state,bot=object())
        self.assertTrue(state.cleared); update.assert_not_called()


if __name__ == "__main__": unittest.main()
