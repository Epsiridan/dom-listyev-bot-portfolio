# -*- coding: utf-8 -*-
"""Точка входа Telegram-бота Дом Листьев."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router

from config import settings
from handlers import (
    admin,
    archive,
    community,
    content_admin,
    contest,
    contest_admin,
    events,
    exploration,
    keeper,
    publication_queue,
    publications,
    start,
    vision,
)
from handlers.keeper import keeper_dialogue_timeout_loop
from services.database import init_db
from services.contests import ensure_echo_contest
from services.events import house_event_reminder_loop
from services.publications import publication_loop

logger = logging.getLogger(__name__)

ROUTERS: tuple[Router, ...] = (
    keeper.router,
    start.router,
    vision.router,
    admin.router,
    archive.router,
    community.router,
    content_admin.router,
    contest.router,
    contest_admin.router,
    events.router,
    exploration.router,
    publication_queue.router,
    publications.router,
)


def configure_logging() -> None:
    """Настроить единый формат логов локально и на Railway."""
    requested_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, requested_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def register_routers(dispatcher: Dispatcher) -> None:
    """Подключить обработчики в предсказуемом порядке."""
    for router in ROUTERS:
        dispatcher.include_router(router)


def create_dispatcher() -> Dispatcher:
    """Собрать Dispatcher отдельно от запуска polling."""
    dispatcher = Dispatcher()
    register_routers(dispatcher)
    return dispatcher


def create_scheduler_tasks(bot: Bot) -> list[asyncio.Task[None]]:
    """Запустить именованные фоновые циклы."""
    return [
        asyncio.create_task(
            publication_loop(bot),
            name="publication_scheduler",
        ),
        asyncio.create_task(
            house_event_reminder_loop(bot),
            name="event_reminder_scheduler",
        ),
        asyncio.create_task(
            keeper_dialogue_timeout_loop(bot),
            name="keeper_dialogue_timeout_scheduler",
        ),
    ]


async def stop_scheduler_tasks(tasks: list[asyncio.Task[None]]) -> None:
    """Отменить фоновые циклы и дождаться остановки."""
    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException) and not isinstance(
            result,
            asyncio.CancelledError,
        ):
            logger.error(
                "Scheduler task ended with an error: %s",
                task.get_name(),
                exc_info=(type(result), result, result.__traceback__),
            )


async def main() -> None:
    """Запустить polling и корректно остановить фоновые задачи."""
    configure_logging()
    init_db()
    ensure_echo_contest()

    bot = Bot(settings.BOT_TOKEN)
    dispatcher = create_dispatcher()
    scheduler_tasks = create_scheduler_tasks(bot)

    logger.info("Dom Listyev bot is starting")
    try:
        await dispatcher.start_polling(bot)
    finally:
        logger.info("Dom Listyev bot is stopping")
        await stop_scheduler_tasks(scheduler_tasks)


if __name__ == "__main__":
    asyncio.run(main())
