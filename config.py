# -*- coding: utf-8 -*-
"""Гибридная конфигурация: ENV → локальный YAML → встроенные значения."""

import os
from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.yaml"

DEFAULTS = {
    "admin_ids": [],
    "data_dir": str(PROJECT_DIR / "data"),
    "timezone": "Europe/Moscow",
    "content_source_thread_id": None,
    "admin_proposals_thread_id": None,
    "admin_contests_thread_id": None,
    "admin_rejects_thread_id": None,
    "publication_hour": 18,
    "publication_minute": 0,
    "openai_vision_model": "gpt-5.6-sol",
}
ENV_NAMES = {
    "general_group_id": "GENERAL_GROUP_ID",
    "admin_group_id": "ADMIN_GROUP_ID",
    "public_channel_id": "PUBLIC_CHANNEL_ID",
    "partner_channel_id": "PARTNER_CHANNEL_ID",
    "admin_ids": "ADMIN_IDS",
    "data_dir": "DATA_DIR",
    "timezone": "TIMEZONE",
    "content_source_thread_id": "CONTENT_SOURCE_THREAD_ID",
    "admin_proposals_thread_id": "ADMIN_PROPOSALS_THREAD_ID",
    "admin_contests_thread_id": "ADMIN_CONTESTS_THREAD_ID",
    "admin_rejects_thread_id": "ADMIN_REJECTS_THREAD_ID",
    "publication_hour": "PUBLICATION_HOUR",
    "publication_minute": "PUBLICATION_MINUTE",
    "openai_vision_model": "OPENAI_VISION_MODEL",
}

def _read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Конфигурация {path} должна содержать YAML-объект")
    return loaded


def _resolve(name: str, config: dict, default=None):
    env_name = ENV_NAMES.get(name, name.upper())
    raw = os.getenv(env_name)
    if raw is not None and raw.strip() != "":
        return raw.strip()
    if name in config and config[name] is not None:
        return config[name]
    return DEFAULTS.get(name, default)


def _required(name: str, config: dict):
    value = _resolve(name, config)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Не задана настройка {ENV_NAMES.get(name, name.upper())}")
    return value


def _parse_int_set(value) -> frozenset[int]:
    if value is None:
        return frozenset()
    items = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    return frozenset(int(str(item).strip()) for item in items if str(item).strip())


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


def _get_required_int_env(name: str) -> int:
    return int(_get_required_env(name))


def _get_optional_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _get_bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = _get_int_env(name, default)
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} должен быть в диапазоне {minimum}..{maximum}, получено: {value}")
    return value


def _get_int_set_env(name: str) -> frozenset[int]:
    return _parse_int_set(os.getenv(name, ""))


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str
    OPENAI_API_KEY: str
    OPENAI_VISION_MODEL: str
    GENERAL_GROUP_ID: int
    ADMIN_GROUP_ID: int
    PUBLIC_CHANNEL_ID: int
    PARTNER_CHANNEL_ID: int
    ADMIN_IDS: frozenset[int]
    DATA_DIR: Path
    DB_PATH: Path
    MOSCOW_TZ: tzinfo
    TIMEZONE_NAME: str
    CONTENT_SOURCE_THREAD_ID: int | None
    ADMIN_PROPOSALS_THREAD_ID: int | None
    ADMIN_CONTESTS_THREAD_ID: int | None
    ADMIN_REJECTS_THREAD_ID: int | None
    PUBLICATION_HOUR: int
    PUBLICATION_MINUTE: int


def _optional_int(value) -> int | None:
    return None if value is None or str(value).strip() == "" else int(value)


def _load_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Europe/Moscow":
            return timezone(timedelta(hours=3), name="MSK")
        raise RuntimeError(f"Не найдена база часовых поясов для {name}")


def load_settings(config_path: Path | None = None) -> Settings:
    config = _read_config(config_path or Path(os.getenv("CONFIG_FILE", DEFAULT_CONFIG_PATH)))
    # BOT_TOKEN and OPENAI_API_KEY are deliberately ENV-only: secrets never come from YAML.
    token = _get_required_env("BOT_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    data_dir = Path(str(_resolve("data_dir", config)))
    hour = int(_resolve("publication_hour", config))
    minute = int(_resolve("publication_minute", config))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise RuntimeError("Время публикации должно быть в допустимом диапазоне")
    timezone_name = str(_resolve("timezone", config))
    return Settings(
        BOT_TOKEN=token,
        OPENAI_API_KEY=openai_api_key,
        OPENAI_VISION_MODEL=str(_resolve("openai_vision_model", config)),
        GENERAL_GROUP_ID=int(_required("general_group_id", config)),
        ADMIN_GROUP_ID=int(_required("admin_group_id", config)),
        PUBLIC_CHANNEL_ID=int(_required("public_channel_id", config)),
        PARTNER_CHANNEL_ID=int(_required("partner_channel_id", config)),
        ADMIN_IDS=_parse_int_set(_resolve("admin_ids", config)),
        DATA_DIR=data_dir,
        DB_PATH=data_dir / "submissions.db",
        MOSCOW_TZ=_load_timezone(timezone_name),
        TIMEZONE_NAME=timezone_name,
        CONTENT_SOURCE_THREAD_ID=_optional_int(_resolve("content_source_thread_id", config)),
        ADMIN_PROPOSALS_THREAD_ID=_optional_int(_resolve("admin_proposals_thread_id", config)),
        ADMIN_CONTESTS_THREAD_ID=_optional_int(_resolve("admin_contests_thread_id", config)),
        ADMIN_REJECTS_THREAD_ID=_optional_int(_resolve("admin_rejects_thread_id", config)),
        PUBLICATION_HOUR=hour,
        PUBLICATION_MINUTE=minute,
    )


settings = load_settings()
