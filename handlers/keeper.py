# -*- coding: utf-8 -*-
"""Одноразовая пасхалка: короткий разговор с настоящим голосом Смотрителя."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from config import settings
from handlers.access import is_admin
from services.database import (
    advance_keeper_dialogue,
    arm_keeper_easter_egg,
    claim_due_keeper_dialogue,
    claim_keeper_easter_egg,
    complete_due_keeper_dialogue,
    find_keeper_person,
    find_keeper_record,
    finish_keeper_dialogue,
    get_active_keeper_dialogue,
    release_due_keeper_dialogue,
    save_keeper_group_message,
    start_keeper_dialogue,
)
from services.exploration import COMMAND_RE, extract_room_name, normalize_room_name
from services.keeper import (
    KEEPER_FINAL_REPLY,
    KEEPER_MAX_REPLIES,
    keeper_opening,
    keeper_reply,
    wants_to_end,
)
from services.telegram_utils import call_telegram_with_retry, thread_kwargs

router = Router()
logger = logging.getLogger(__name__)

ARM_KEEPER_PATTERN = r"(?i)^\s*смотритель,\s*проснись[.!]?\s*$"
TIMEOUT_CHECK_SECONDS = 60
ACTIVE_KEEPER_DIALOGUES: set[int] = set()


def _message_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _remember_message(message: Message) -> None:
    """Локально запомнить только человеческий текст из основной группы."""
    author = message.from_user
    text = _message_text(message)
    if not author or author.is_bot or not text:
        return
    try:
        save_keeper_group_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=message.message_thread_id,
            user_id=author.id,
            username=author.username,
            full_name=author.full_name,
            text=text,
            sent_at=message.date.isoformat(timespec="seconds"),
        )
    except Exception:
        logger.exception(
            "Failed to remember group message: chat_id=%s message_id=%s",
            message.chat.id,
            message.message_id,
        )


async def _reply(message: Message, text: str) -> Message | None:
    try:
        return await call_telegram_with_retry(
            lambda: message.reply(text),
            operation_name="send keeper dialogue reply",
        )
    except TelegramBadRequest:
        try:
            return await call_telegram_with_retry(
                lambda: message.answer(text),
                operation_name="send keeper dialogue fallback",
            )
        except TelegramAPIError:
            logger.exception("Failed to send keeper fallback")
            return None
    except TelegramAPIError:
        logger.exception("Failed to send keeper reply")
        return None


@router.message(F.text.regexp(ARM_KEEPER_PATTERN))
async def arm_keeper(message: Message) -> None:
    """Скрытая админская фраза взводит ровно одну следующую пасхалку."""
    if not message.from_user or not is_admin(message.from_user.id):
        raise SkipHandler()
    arm_keeper_easter_egg(armed_by=message.from_user.id)
    await message.answer(
        "Я не спал. Просто не отвечал. Следующую дверь открою сам."
    )


@router.message(
    F.chat.id == settings.GENERAL_GROUP_ID,
    F.reply_to_message,
)
async def continue_keeper_dialogue(message: Message) -> None:
    """Отвечать только на прямой ответ к последней реплике активного Смотрителя."""
    text = _message_text(message)
    author = message.from_user
    if not text or not author or author.is_bot or text.startswith("/"):
        raise SkipHandler()

    _remember_message(message)
    dialogue = get_active_keeper_dialogue(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
    )
    if (
        dialogue is None
        or message.reply_to_message is None
        or message.reply_to_message.message_id != dialogue["last_bot_message_id"]
    ):
        raise SkipHandler()

    dialogue_id = int(dialogue["id"])
    if dialogue_id in ACTIVE_KEEPER_DIALOGUES:
        raise SkipHandler()
    ACTIVE_KEEPER_DIALOGUES.add(dialogue_id)
    try:
        next_reply_number = int(dialogue["reply_count"]) + 1
        person = find_keeper_person(message.chat.id, text)
        person_name = str(person["full_name"]) if person is not None else None
        memory_record = find_keeper_record(text)
        answer = keeper_reply(
            text,
            reply_number=next_reply_number,
            room_name=str(dialogue["room_name"]),
            person_name=person_name,
            memory_record=memory_record,
        )
        sent = await _reply(message, answer)
        if sent is None:
            return

        must_finish = next_reply_number >= KEEPER_MAX_REPLIES or wants_to_end(text)
        advance_keeper_dialogue(
            dialogue_id=dialogue_id,
            last_bot_message_id=sent.message_id,
            finish=must_finish,
        )
    finally:
        ACTIVE_KEEPER_DIALOGUES.discard(dialogue_id)


@router.message(
    F.chat.id == settings.GENERAL_GROUP_ID,
    F.text.regexp(COMMAND_RE),
)
async def maybe_awaken_keeper(message: Message) -> None:
    """Перехватить следующий корректный запрос, только если пасхалка взведена."""
    raw_room_name = extract_room_name(message.text)
    if not raw_room_name or not message.from_user or message.from_user.is_bot:
        raise SkipHandler()
    if not claim_keeper_easter_egg(claimed_by=message.from_user.id):
        raise SkipHandler()

    _remember_message(message)
    room = normalize_room_name(raw_room_name)
    sent = await _reply(message, keeper_opening(room.display_name))
    if sent is None:
        arm_keeper_easter_egg(armed_by=0)
        return

    start_keeper_dialogue(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
        trigger_user_id=message.from_user.id,
        room_name=room.display_name,
        last_bot_message_id=sent.message_id,
    )


@router.message(F.chat.id == settings.GENERAL_GROUP_ID)
async def remember_group_message(message: Message) -> None:
    """Наблюдать за новыми сообщениями, не мешая остальным обработчикам."""
    _remember_message(message)
    raise SkipHandler()


async def keeper_dialogue_timeout_loop(bot: Bot) -> None:
    """Через три часа самому закрыть незавершённый разговор."""
    while True:
        try:
            dialogue = claim_due_keeper_dialogue()
            while dialogue is not None:
                dialogue_id = int(dialogue["id"])
                try:
                    await call_telegram_with_retry(
                        lambda: bot.send_message(
                            chat_id=int(dialogue["chat_id"]),
                            text=KEEPER_FINAL_REPLY,
                            **thread_kwargs(dialogue["message_thread_id"]),
                        ),
                        operation_name="send keeper timeout closing",
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    logger.exception(
                        "Keeper dialogue cannot be closed in Telegram: dialogue_id=%s",
                        dialogue_id,
                    )
                    finish_keeper_dialogue(dialogue_id)
                except TelegramAPIError:
                    logger.exception(
                        "Failed to close keeper dialogue: dialogue_id=%s",
                        dialogue_id,
                    )
                    release_due_keeper_dialogue(dialogue_id)
                    break
                else:
                    complete_due_keeper_dialogue(dialogue_id)
                dialogue = claim_due_keeper_dialogue()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Keeper timeout loop failed")

        await asyncio.sleep(TIMEOUT_CHECK_SECONDS)
