# -*- coding: utf-8 -*-
"""Каталог, fallback-логика и Telegram-отправка редактируемого контента."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from aiogram.types import Message

from config import PROJECT_DIR
from services.database import delete_content_override, get_content_override, save_content_override
from services.telegram_utils import split_text_chunks

DEFAULTS_PATH = PROJECT_DIR / "content.defaults.yaml"
EMERGENCY = {
    "main_menu": {"title": "Главное приветствие", "text": "🍃 Добро пожаловать в Дом Листьев.", "send_mode": "auto"},
    "community_rules": {"title": "Правила сообщества", "text": "Пожалуйста, соблюдайте правила сообщества.", "send_mode": "auto"},
}
VALID_MODES = {"auto", "text", "caption", "separate"}

@dataclass(frozen=True)
class ContentBlock:
    key: str
    title: str
    text: str
    image_file_id: str | None
    send_mode: str
    is_custom: bool
    updated_at: str | None = None
    updated_by: int | None = None

@lru_cache(maxsize=1)
def load_default_catalog() -> dict[str, dict]:
    try:
        data = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {}
        blocks = data.get("blocks", {})
        return blocks if isinstance(blocks, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}

def content_keys() -> tuple[str, ...]:
    return tuple(load_default_catalog())

def get_content_block(key: str) -> ContentBlock:
    default = load_default_catalog().get(key) or EMERGENCY.get(key) or {
        "title": key, "text": "Сообщение временно недоступно.", "send_mode": "auto"
    }
    override = get_content_override(key)
    if override:
        return ContentBlock(key, override["title"] or default.get("title", key),
            override["text"] if override["text"] is not None else str(default.get("text", "")),
            override["image_file_id"], override["send_mode"], True,
            override["updated_at"], override["updated_by"])
    return ContentBlock(key, str(default.get("title", key)), str(default.get("text", "")),
        None, str(default.get("send_mode", "auto")), False)

def get_text(key: str, fallback: str = "Сообщение временно недоступно.") -> str:
    text = get_content_block(key).text
    return text if text else fallback

def save_block(block: ContentBlock, *, updated_by: int) -> None:
    save_content_override(content_key=block.key, title=block.title, text=block.text,
        image_file_id=block.image_file_id, send_mode=block.send_mode, updated_by=updated_by)

def reset_block(key: str) -> bool:
    return delete_content_override(key)

async def send_content(message: Message, key: str, *, reply_markup=None, values: dict[str, str] | None = None, suffix: str = "") -> list[Message]:
    """Отправить блок, учитывая caption 1024 и длинные тексты."""
    block = get_content_block(key)
    text=block.text
    for placeholder, value in (values or {}).items():
        text=text.replace("{" + placeholder + "}", value)
    text += suffix
    sent=[]
    mode=block.send_mode
    if not block.image_file_id or mode == "text":
        chunks=split_text_chunks(text)
        for index, chunk in enumerate(chunks):
            sent.append(await message.answer(chunk, reply_markup=reply_markup if index == len(chunks)-1 else None))
        return sent
    use_caption = mode in {"auto", "caption"} and len(text) <= 1024
    if use_caption:
        sent.append(await message.answer_photo(block.image_file_id, caption=text, reply_markup=reply_markup))
        return sent
    sent.append(await message.answer_photo(block.image_file_id))
    chunks=split_text_chunks(text)
    for index, chunk in enumerate(chunks):
        sent.append(await message.answer(chunk, reply_markup=reply_markup if index == len(chunks)-1 else None))
    return sent
