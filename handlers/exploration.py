# -*- coding: utf-8 -*-
"""Игровые исследования комнат и скрытый личный журнал."""

import asyncio
import logging
import random
from dataclasses import dataclass, replace

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message

from services.database import (
    get_last_room_exploration_time,
    get_room_exploration_journal,
    get_room_exploration_time,
    save_room_exploration,
)
from services.exploration import (
    COMMAND_RE,
    ExplorationReport,
    RoomIdentity,
    choose_exploration_report,
    choose_revisit_note,
    extract_room_name,
    format_exploration_report,
    format_remaining_cooldown,
    get_cooldown_remaining,
    normalize_room_name,
)
from services.telegram_utils import call_telegram_with_retry, split_text_chunks

router = Router()
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExplorationProgressStep:
    """Один экран анимации и время, которое он виден."""

    text: str
    min_delay: float
    max_delay: float

    def delay(self) -> float:
        return random.uniform(self.min_delay, self.max_delay)


EXPLORATION_PROGRESS_STEPS: tuple[ExplorationProgressStep, ...] = (
    ExplorationProgressStep("Смотритель ищет нужную комнату…", 1, 2),
    ExplorationProgressStep("Подбираем ключи…", 1, 2),
    ExplorationProgressStep("Исследуем пространство, следы и отклик Дома…", 2, 4),
)
ACTIVE_EXPLORATIONS: set[int] = set()


async def _edit_or_answer(
    source_message: Message,
    progress_message: Message | None,
    text: str,
) -> Message | None:
    """Обновить прогресс, а после ошибки отправить отдельное сообщение."""
    if progress_message is not None:
        try:
            return await call_telegram_with_retry(
                lambda: progress_message.edit_text(text),
                operation_name="edit room exploration progress",
            )
        except TelegramBadRequest as error:
            logger.info("Cannot edit exploration progress; using fallback: %s", error)
        except TelegramAPIError as error:
            logger.warning("Cannot edit exploration progress; using fallback: %s", error)

    try:
        return await call_telegram_with_retry(
            lambda: source_message.answer(text),
            operation_name="send room exploration fallback",
        )
    except TelegramAPIError:
        logger.exception("Failed to deliver room exploration message")
        return None


async def _run_exploration_progress(
    source_message: Message,
    progress_message: Message,
) -> Message:
    """Показать этапы; сбой одного этапа не отменяет финальный результат."""
    current_message = progress_message
    for index, step in enumerate(EXPLORATION_PROGRESS_STEPS):
        if index:
            updated_message = await _edit_or_answer(
                source_message,
                current_message,
                step.text,
            )
            if updated_message is not None:
                current_message = updated_message
        await asyncio.sleep(step.delay())
    return current_message


async def _complete_exploration(
    source_message: Message,
    progress_message: Message | None,
    *,
    user_id: int,
    room: RoomIdentity,
    report: ExplorationReport,
    final_text: str,
) -> bool:
    """Доставить итог и лишь затем атомарно сохранить историю и кулдаун."""
    delivered_message = await _edit_or_answer(
        source_message,
        progress_message,
        final_text,
    )
    if delivered_message is None:
        logger.error(
            "Exploration result was not delivered; history not saved: user_id=%s room=%s",
            user_id,
            room.key,
        )
        return False

    try:
        save_room_exploration(
            user_id=user_id,
            room_key=room.key,
            room_name=room.display_name,
            space_result=report.space,
            traces_result=report.traces,
            response_result=report.response,
            revisit_note=report.revisit_note,
        )
    except Exception:
        logger.exception(
            "Failed to save exploration result: user_id=%s room=%s",
            user_id,
            room.key,
        )
    return True


@router.message(F.text.regexp(r"(?i)^\s*мой\s+журнал[.!?]?\s*$"))
async def show_my_exploration_journal(message: Message) -> None:
    """Показать скрытый журнал пользователя без кнопок и меню."""
    if not message.from_user:
        await message.answer("Не удалось определить владельца журнала.")
        return

    entries = get_room_exploration_journal(message.from_user.id)
    if not entries:
        await message.answer(
            "📖 Журнал исследователя\n\n"
            "Страницы пока пусты. Смотритель ещё не записал ни одной исследованной комнаты."
        )
        return

    total_explorations = sum(int(entry["exploration_count"]) for entry in entries)
    lines = ["📖 Журнал исследователя", ""]
    for entry in entries:
        lines.append(
            f"«{entry['room_name']}» — проведено исследований: "
            f"{entry['exploration_count']}"
        )

    lines.extend(
        [
            "",
            f"Всего исследований: {total_explorations}",
            f"Исследовано комнат: {len(entries)}",
        ]
    )
    for chunk in split_text_chunks("\n".join(lines)):
        await message.answer(chunk)


@router.message(F.text.regexp(COMMAND_RE))
async def explore_room(message: Message) -> None:
    """Исследовать три аспекта комнаты и сохранить результат в журнал."""
    raw_room_name = extract_room_name(message.text)
    if raw_room_name is None:
        return
    if not raw_room_name:
        await message.answer(
            "Укажите комнату для исследования. Например: /исследуй Архив №7",
        )
        return
    if not message.from_user:
        await message.answer("Не удалось определить исследователя.")
        return

    user_id = message.from_user.id
    remaining = get_cooldown_remaining(get_room_exploration_time(user_id))
    if remaining is not None:
        await message.answer(
            "Вы уже исследовали комнату недавно.\n"
            f"Следующее исследование будет доступно через {format_remaining_cooldown(remaining)}.",
        )
        return
    if user_id in ACTIVE_EXPLORATIONS:
        await message.answer(
            "Смотритель уже исследует вашу комнату. Результат появится через несколько секунд.",
        )
        return

    room = normalize_room_name(raw_room_name)
    if not room.key:
        await message.answer("Название комнаты не должно состоять только из кавычек.")
        return

    previous_visit = get_last_room_exploration_time(user_id, room.key)
    report = choose_exploration_report(room)
    report = replace(
        report,
        revisit_note=choose_revisit_note(
            previous_visit,
            special_key=room.special_key,
        ),
    )
    final_text = format_exploration_report(room, report)

    ACTIVE_EXPLORATIONS.add(user_id)
    progress_message: Message | None = None
    try:
        try:
            progress_message = await call_telegram_with_retry(
                lambda: message.answer(EXPLORATION_PROGRESS_STEPS[0].text),
                operation_name="start room exploration progress",
            )
        except TelegramAPIError:
            logger.exception("Failed to start exploration: user_id=%s", user_id)

        if progress_message is not None:
            progress_message = await _run_exploration_progress(
                message,
                progress_message,
            )

        await _complete_exploration(
            message,
            progress_message,
            user_id=user_id,
            room=room,
            report=report,
            final_text=final_text,
        )
    except asyncio.CancelledError:
        logger.warning(
            "Exploration cancelled; attempting final delivery: user_id=%s",
            user_id,
        )
        try:
            await asyncio.wait_for(
                asyncio.shield(
                    _complete_exploration(
                        message,
                        progress_message,
                        user_id=user_id,
                        room=room,
                        report=report,
                        final_text=final_text,
                    )
                ),
                timeout=3,
            )
        except Exception:
            logger.exception(
                "Final exploration delivery during shutdown failed: user_id=%s",
                user_id,
            )
        raise
    finally:
        ACTIVE_EXPLORATIONS.discard(user_id)
