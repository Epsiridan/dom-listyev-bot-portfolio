# -*- coding: utf-8 -*-
"""Административный редактор базовых текстов и оформления."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.access import is_admin, require_private_admin_callback
from handlers.screens import safe_edit_or_answer
from keyboards_parts.content import (
    content_cancel_keyboard, content_confirm_keyboard, content_detail_keyboard,
    content_list_keyboard, content_mode_keyboard, content_reset_confirm_keyboard,
)
from services.content import ContentBlock, content_keys, get_content_block, reset_block, save_block, send_content
from states import ContentAdmin

router=Router()
MODE_LABELS={"auto":"Автоматически", "text":"Только текст", "caption":"Фото с подписью", "separate":"Фото, затем текст"}

async def _allowed(callback):
    return await require_private_admin_callback(callback, "Редактор текстов доступен только администраторам в личке.")

def _key(data: str | None, index: int = 1) -> str:
    return (data or "").split(":")[index]

def _clip(text: str, limit: int = 2800) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…"

async def _show_detail(target, key: str) -> None:
    block=get_content_block(key)
    status="изменён администратором" if block.is_custom else "стандартный"
    text=(f"📝 {block.title}\n\nКлюч: {block.key}\nИсточник: {status}\n"
          f"Изображение: {'есть' if block.image_file_id else 'нет'}\n"
          f"Режим: {MODE_LABELS.get(block.send_mode, block.send_mode)}\n"
          f"Изменено: {block.updated_at or '—'}\nКем: {block.updated_by or '—'}\n\n"
          f"Текущее значение:\n«{_clip(block.text)}»")
    markup=content_detail_keyboard(key, has_image=bool(block.image_file_id), is_custom=block.is_custom)
    if isinstance(target, CallbackQuery):
        await safe_edit_or_answer(target,text,reply_markup=markup)
    else:
        await target.answer(text,reply_markup=markup)

@router.callback_query(F.data == "admin_content")
async def content_home(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    await state.clear()
    blocks=[get_content_block(key) for key in content_keys()]
    await safe_edit_or_answer(callback,"🎨 Тексты и оформление\n\nВыберите текстовый блок:",reply_markup=content_list_keyboard(blocks))
    await callback.answer()

@router.callback_query(F.data.startswith("content_view:"))
async def content_view(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    await state.clear(); await _show_detail(callback,_key(callback.data)); await callback.answer()

@router.callback_query(F.data.startswith("content_text:"))
async def content_text_start(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data); block=get_content_block(key)
    await state.clear(); await state.update_data(content_key=key, edit_kind="text")
    await state.set_state(ContentAdmin.waiting_text)
    await safe_edit_or_answer(callback,f"Текущее значение:\n«{_clip(block.text)}»\n\nОтправьте новое значение.",reply_markup=content_cancel_keyboard(key))
    await callback.answer()

@router.message(ContentAdmin.waiting_text, F.chat.type == "private")
async def content_text_received(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id): return
    text=(message.text or message.caption or "").strip()
    if not text:
        await message.answer("Нужен непустой текст."); return
    if len(text)>12000:
        await message.answer("Текст слишком длинный. Максимум — 12 000 символов."); return
    data=await state.get_data(); key=data["content_key"]; old=get_content_block(key).text
    await state.update_data(pending_value=text); await state.set_state(ContentAdmin.confirming)
    await message.answer(f"Было:\n«{_clip(old,1400)}»\n\nСтанет:\n«{_clip(text,1400)}»",reply_markup=content_confirm_keyboard(key))

@router.callback_query(F.data.startswith("content_image:"))
async def content_image_start(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data); block=get_content_block(key)
    current=block.image_file_id or "изображения нет"
    await state.clear(); await state.update_data(content_key=key,edit_kind="image")
    await state.set_state(ContentAdmin.waiting_image)
    await safe_edit_or_answer(callback,f"Текущее значение:\n«{current}»\n\nОтправьте новое изображение как фото.",reply_markup=content_cancel_keyboard(key)); await callback.answer()

@router.message(ContentAdmin.waiting_image, F.chat.type == "private")
async def content_image_received(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id): return
    if not message.photo:
        await message.answer("Отправьте изображение как фото."); return
    data=await state.get_data(); key=data["content_key"]; old=get_content_block(key).image_file_id or "нет"
    new=message.photo[-1].file_id
    await state.update_data(pending_value=new); await state.set_state(ContentAdmin.confirming)
    await message.answer(f"Было изображение: {old}\nСтанет: {new}",reply_markup=content_confirm_keyboard(key))

@router.callback_query(F.data.startswith("content_image_delete:"))
async def content_image_delete(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data,1); block=get_content_block(key)
    await state.clear(); await state.update_data(content_key=key,edit_kind="image",pending_value=None)
    await state.set_state(ContentAdmin.confirming)
    await safe_edit_or_answer(callback,f"Было изображение: {block.image_file_id or 'нет'}\nСтанет: без изображения",reply_markup=content_confirm_keyboard(key)); await callback.answer()

@router.callback_query(F.data.startswith("content_mode:"))
async def content_mode_start(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data); block=get_content_block(key)
    await state.clear(); await state.update_data(content_key=key,edit_kind="mode")
    await safe_edit_or_answer(callback,f"Текущее значение:\n«{MODE_LABELS.get(block.send_mode,block.send_mode)}»\n\nВыберите новое значение.",reply_markup=content_mode_keyboard(key)); await callback.answer()

@router.callback_query(F.data.startswith("content_mode_pick:"))
async def content_mode_pick(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    _,key,mode=callback.data.split(":",2); old=get_content_block(key).send_mode
    await state.update_data(content_key=key,edit_kind="mode",pending_value=mode); await state.set_state(ContentAdmin.confirming)
    await safe_edit_or_answer(callback,f"Было:\n«{MODE_LABELS[old]}»\n\nСтанет:\n«{MODE_LABELS[mode]}»",reply_markup=content_confirm_keyboard(key)); await callback.answer()

@router.callback_query(F.data.startswith("content_save:"))
async def content_save(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    data=await state.get_data(); key=_key(callback.data); block=get_content_block(key); kind=data.get("edit_kind"); value=data.get("pending_value")
    updated=ContentBlock(key,block.title,value if kind=="text" else block.text,
        value if kind=="image" else block.image_file_id,
        value if kind=="mode" else block.send_mode,True)
    save_block(updated,updated_by=callback.from_user.id); await state.clear(); await _show_detail(callback,key); await callback.answer("Сохранено")

@router.callback_query(F.data.startswith("content_retry:"))
async def content_retry(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    data=await state.get_data(); key=_key(callback.data); kind=data.get("edit_kind")
    if kind=="text":
        await state.set_state(ContentAdmin.waiting_text); prompt="Отправьте новое значение."
    elif kind=="image":
        await state.set_state(ContentAdmin.waiting_image); prompt="Отправьте новое изображение как фото."
    else:
        await state.set_state(None); await safe_edit_or_answer(callback,"Выберите новое значение.",reply_markup=content_mode_keyboard(key)); await callback.answer(); return
    await safe_edit_or_answer(callback,prompt,reply_markup=content_cancel_keyboard(key)); await callback.answer()

@router.callback_query(F.data.startswith("content_cancel:"))
async def content_cancel(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data); await state.clear(); await _show_detail(callback,key); await callback.answer("Изменения отменены")

@router.callback_query(F.data.startswith("content_reset:"))
async def content_reset_start(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data); block=get_content_block(key)
    await state.clear(); await safe_edit_or_answer(callback,f"Текущее значение — пользовательское.\n\nСбросить блок «{block.title}» к стандартному тексту и удалить его изображение?",reply_markup=content_reset_confirm_keyboard(key)); await callback.answer()

@router.callback_query(F.data.startswith("content_reset_confirm:"))
async def content_reset_confirm(callback: CallbackQuery, state: FSMContext):
    if not await _allowed(callback): return
    key=_key(callback.data,1); reset_block(key); await state.clear(); await _show_detail(callback,key); await callback.answer("Сброшено")

@router.callback_query(F.data.startswith("content_preview:"))
async def content_preview(callback: CallbackQuery):
    if not await _allowed(callback): return
    key=_key(callback.data); await send_content(callback.message,key,reply_markup=content_cancel_keyboard(key)); await callback.answer()
