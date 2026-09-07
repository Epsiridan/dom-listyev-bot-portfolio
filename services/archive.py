# -*- coding: utf-8 -*-
"""Данные и форматирование публичного архива Дома Листьев."""

from services.contest_database import (
    count_contest_submissions,
    get_archived_contests as get_archived_contests_from_db,
    get_contest,
)
from services.contests import format_contest_datetime, plain_from_html


def _shorten(value: str, limit: int = 650) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def get_archived_contests() -> list:
    return get_archived_contests_from_db()


def get_archived_contest(contest_id: str | int):
    try:
        numeric_id = int(contest_id)
    except (TypeError, ValueError):
        return None
    archived_ids = {int(row["id"]) for row in get_archived_contests_from_db(limit=100)}
    if numeric_id not in archived_ids:
        return None
    return get_contest(numeric_id)


def build_archived_contest_text(contest) -> str:
    description = _shorten(plain_from_html(contest["description_html"]))
    return (
        f"🎨 {contest['title']}\n\n"
        f"Период: {format_contest_datetime(contest['starts_at'])} — "
        f"{format_contest_datetime(contest['ends_at'])}\n\n"
        f"{description}\n\n"
        f"Принято работ: {count_contest_submissions(int(contest['id']))}"
    )


def shorten_archive_description(value: str, limit: int = 650) -> str:
    return _shorten(value, limit=limit)
