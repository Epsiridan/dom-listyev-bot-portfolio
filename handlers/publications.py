# -*- coding: utf-8 -*-
"""Обработчики пользовательской предложки и админской модерации листов."""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import settings
from handlers.access import is_admin
from handlers.screens import safe_edit_or_answer, send_content_screen
from keyboards_parts.editing import edit_confirm_keyboard, edit_prompt_keyboard
from keyboards import (
    author_visibility_keyboard,
    creative_group_keyboard,
    propose_post_rules_keyboard,
    proposed_post_review_keyboard,
    restart_keyboard,
)
from services.database import (
    approve_proposed_post,
    get_proposed_post,
    reject_proposed_post,
    update_proposed_post_text,
)
from services.publications import (
    build_review_text_from_post,
    build_submission_data_from_message,
    create_review_for_submission_data,
    extract_creative_group_from_message,
    extract_publication_text,
    format_scheduled_for,
    has_new_leaf_trigger,
    notify_author_about_approval,
    parse_mode_for_text_format,
    publish_proposed_post_now,
    send_rejected_post_to_archive,
    send_stored_review_card,
)
from services.telegram_utils import callback_int_id, thread_kwargs
from states import ProposedPostModeration, ProposedPostSubmission
from services.content import get_text, send_content

router = Router()
PROPOSED_POST_TTL_SECONDS = 60 * 60
AUTHOR_VISIBILITY_YES_VALUES = {
    "да",
    "yes",
    "y",
    "+",
    "указать",
    "указать автора",
    "да, указать автора",
}
AUTHOR_VISIBILITY_NO_VALUES = {
    "нет",
    "no",
    "n",
    "-",
    "анонимно",
    "без автора",
    "нет, опубликовать анонимно",
}


def _edit_preview(value: str | None, limit: int = 1600) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + "\n…"


# --- Общие проверки личной предложки и очистка временных сообщений ----------

def _is_source_topic(message: Message) -> bool:
    """Проверить, что команда пришла из разрешённого топика-источника."""
    return message.message_thread_id == settings.CONTENT_SOURCE_THREAD_ID


def _is_group_message(message: Message) -> bool:
    """Отличить групповой сценарий от личной предложки."""
    return message.chat.type in {"group", "supergroup"}


async def _delete_message_later(bot: Bot, chat_id: int, message_id: int, delay: int = 20) -> None:
    """Удалить временное служебное сообщение после паузы."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _send_temporary_group_reply(
    bot: Bot,
    message: Message,
    text: str,
    delay: int = 30,
) -> None:
    """Ответить в группе и автоматически убрать подсказку через delay секунд."""
    sent = await message.reply(text)
    asyncio.create_task(_delete_message_later(bot, sent.chat.id, sent.message_id, delay))


async def _remember_cleanup_message(state: FSMContext, sent: Message) -> None:
    """Запомнить сообщение бота, которое надо удалить после оформления листа."""
    data = await state.get_data()
    if not data.get("cleanup_group_bot_messages"):
        return

    messages = list(data.get("cleanup_bot_message_ids") or [])
    messages.append({"chat_id": sent.chat.id, "message_id": sent.message_id})
    await state.update_data(cleanup_bot_message_ids=messages)


async def _remember_user_cleanup_message(state: FSMContext, message: Message) -> None:
    """Запомнить пользовательский ответ в группе для последующей уборки."""
    data = await state.get_data()
    if not data.get("cleanup_group_bot_messages"):
        return

    messages = list(data.get("cleanup_user_message_ids") or [])
    messages.append({"chat_id": message.chat.id, "message_id": message.message_id})
    await state.update_data(cleanup_user_message_ids=messages)


async def _answer_and_remember(
    message: Message,
    state: FSMContext,
    text: str,
    **kwargs,
) -> Message:
    """Отправить ответ и, если нужно, добавить его в список уборки."""
    sent = await message.answer(text, **kwargs)
    await _remember_cleanup_message(state, sent)
    return sent


async def _content_and_remember(message: Message, state: FSMContext, key: str, *, reply_markup=None) -> list[Message]:
    sent_messages = await send_content(message, key, reply_markup=reply_markup)
    for sent in sent_messages:
        await _remember_cleanup_message(state, sent)
    return sent_messages


async def _delete_remembered_cleanup_messages(bot: Bot, messages: list[dict]) -> None:
    """Удалить сохранённые служебные сообщения, игнорируя права/устаревание."""
    for item in messages:
        try:
            await bot.delete_message(
                chat_id=item["chat_id"],
                message_id=item["message_id"],
            )
        except Exception:
            pass


def _message_is_submitter(message: Message, data: dict) -> bool:
    """В группе продолжать оформление может только автор исходной команды."""
    submitter_user_id = data.get("submitter_user_id")
    if submitter_user_id is None:
        return True
    return bool(message.from_user and message.from_user.id == submitter_user_id)


def _callback_is_submitter(callback: CallbackQuery, data: dict) -> bool:
    """То же ограничение для inline-кнопок."""
    submitter_user_id = data.get("submitter_user_id")
    if submitter_user_id is None:
        return True
    return callback.from_user.id == submitter_user_id


def _submission_is_expired(data: dict) -> bool:
    """Проверить TTL черновика предложенного поста."""
    expires_at = data.get("expires_at")
    if not expires_at:
        return False

    try:
        return datetime.now(settings.MOSCOW_TZ) >= datetime.fromisoformat(expires_at)
    except ValueError:
        return False


async def _expire_current_proposed_post_submission(bot: Bot, state: FSMContext) -> None:
    """Сбросить просроченный черновик и убрать служебные сообщения."""
    data = await state.get_data()
    cleanup_messages = list(data.get("cleanup_bot_message_ids") or [])
    await state.clear()
    await _delete_remembered_cleanup_messages(bot, cleanup_messages)


async def _expire_proposed_post_submission_later(
    bot: Bot,
    state: FSMContext,
    token: str,
) -> None:
    """Фоновый таймер: через TTL очистить всё ещё активный черновик."""
    await asyncio.sleep(PROPOSED_POST_TTL_SECONDS)
    data = await state.get_data()
    if data.get("proposed_post_token") != token:
        return

    current_state = await state.get_state()
    if current_state not in {
        ProposedPostSubmission.waiting_creative_group.state,
        ProposedPostSubmission.waiting_author_visibility.state,
    }:
        return

    await _expire_current_proposed_post_submission(bot, state)


async def _reject_if_wrong_submitter_message(message: Message, state: FSMContext) -> bool:
    """Вернуть True, если сообщение пришло не от автора сценария."""
    data = await state.get_data()
    return not _message_is_submitter(message, data)


async def _reject_if_wrong_submitter_callback(callback: CallbackQuery, state: FSMContext) -> bool:
    """Вернуть True и показать alert, если кнопку нажал не автор сценария."""
    data = await state.get_data()
    if _callback_is_submitter(callback, data):
        return False

    await callback.answer("Это оформление начал другой участник.", show_alert=True)
    return True


async def _reject_if_expired_message(message: Message, state: FSMContext, bot: Bot) -> bool:
    """Вернуть True, если черновик истёк, и объяснить это пользователю."""
    data = await state.get_data()
    if not _submission_is_expired(data):
        return False

    await _expire_current_proposed_post_submission(bot, state)
    if _is_group_message(message):
        await _send_temporary_group_reply(
            bot,
            message,
            "Время оформления листа истекло. Пожалуйста, начните заново командой «новый лист».",
        )
    else:
        await message.answer(
            "Время оформления листа истекло. Пожалуйста, начните заново."
        )
    return True


async def _reject_if_expired_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> bool:
    """То же для callback-кнопок."""
    data = await state.get_data()
    if not _submission_is_expired(data):
        return False

    await _expire_current_proposed_post_submission(bot, state)
    await callback.answer(
        "Время оформления листа истекло. Пожалуйста, начните заново.",
        show_alert=True,
    )
    return True


async def _ask_creative_group(
    message: Message,
    state: FSMContext,
    post_data: dict,
    bot: Bot,
) -> None:
    """Сохранить черновик поста и спросить творческую группу."""
    token = uuid4().hex
    cleanup_group_messages = _is_group_message(message)
    cleanup_user_messages = []
    if cleanup_group_messages:
        cleanup_user_messages.append(
            {"chat_id": message.chat.id, "message_id": message.message_id}
        )

    await state.set_state(ProposedPostSubmission.waiting_creative_group)
    await state.update_data(
        proposed_post=post_data,
        submitter_user_id=message.from_user.id if message.from_user else None,
        proposed_post_token=token,
        expires_at=(
            datetime.now(settings.MOSCOW_TZ) + timedelta(seconds=PROPOSED_POST_TTL_SECONDS)
        ).isoformat(timespec="seconds"),
        cleanup_group_bot_messages=cleanup_group_messages,
        cleanup_user_message_ids=cleanup_user_messages,
    )
    asyncio.create_task(_expire_proposed_post_submission_later(bot, state, token))
    await _content_and_remember(message, state, "creative_group_prompt", reply_markup=creative_group_keyboard)


async def _ask_author_visibility(
    message: Message,
    state: FSMContext,
    creative_group: str | None,
    creative_group_format: str = "plain",
) -> None:
    """Сохранить группу и спросить, публиковать ли автора."""
    data = await state.get_data()
    post_data = data.get("proposed_post")
    if not post_data:
        await state.clear()
        raise RuntimeError("Нет данных предложенного поста")

    post_data["creative_group"] = creative_group
    post_data["creative_group_format"] = creative_group_format if creative_group else "plain"
    await state.set_state(ProposedPostSubmission.waiting_author_visibility)
    await state.update_data(proposed_post=post_data)
    await _content_and_remember(message, state, "author_visibility_prompt", reply_markup=author_visibility_keyboard)


async def _finish_proposed_post_submission(
    *,
    bot: Bot,
    state: FSMContext,
    publish_author: bool,
) -> tuple[int, list[dict]]:
    """Создать админскую карточку модерации и вернуть ID листа."""
    data = await state.get_data()
    post_data = data.get("proposed_post")
    if not post_data:
        await state.clear()
        raise RuntimeError("Нет данных предложенного поста")

    cleanup_messages = list(data.get("cleanup_bot_message_ids") or [])
    cleanup_messages.extend(data.get("cleanup_user_message_ids") or [])
    post_data["publish_author"] = publish_author
    post_id = await create_review_for_submission_data(bot, post_data)
    await state.clear()
    return post_id, cleanup_messages


# --- Пользовательская предложка: правила, контент и данные автора -----------

@router.callback_query(F.data == "propose_post_info")
async def propose_post_info(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать правила пользовательской предложки."""
    await state.clear()
    await send_content_screen(callback, "propose_post_rules", reply_markup=propose_post_rules_keyboard)
    await callback.answer()


@router.callback_query(F.data == "propose_post_accept_rules")
async def accept_propose_post_rules(callback: CallbackQuery, state: FSMContext) -> None:
    """После принятия правил перейти к ожиданию контента."""
    await state.set_state(ProposedPostSubmission.waiting_content)
    await send_content_screen(callback, "propose_post_content_prompt")
    await callback.answer()


@router.message(ProposedPostSubmission.waiting_content)
async def receive_private_proposed_post(message: Message, state: FSMContext, bot: Bot) -> None:
    """Принять пост, отправленный пользователем в личке бота."""
    text = extract_publication_text(message)
    if not text:
        await message.answer(
            "Не вижу текста поста. Пришлите текст обычным сообщением "
            "или подписью к картинке/аудио."
        )
        return

    post_data = build_submission_data_from_message(message, text=text)
    await _ask_creative_group(message, state, post_data, bot)


@router.message(F.text.regexp(r"(?i)@DomListyevBot\s+id"))
async def mention_topic_id(message: Message) -> None:
    """Быстрая диагностика ID топика через упоминание бота."""
    if message.chat.type not in {"group", "supergroup"}:
        return

    await message.reply(
        "chat_id: `{chat_id}`\nmessage_thread_id: `{thread_id}`".format(
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
        ),
        parse_mode="Markdown",
    )


@router.message(F.chat.id == settings.GENERAL_GROUP_ID)
async def collect_new_leaf_request(message: Message, state: FSMContext, bot: Bot) -> None:
    """Собрать новый лист из группового топика по триггеру."""
    trigger_text = message.text or message.caption or ""
    if not has_new_leaf_trigger(trigger_text):
        raise SkipHandler()

    if settings.CONTENT_SOURCE_THREAD_ID is None:
        await _send_temporary_group_reply(
            bot,
            message,
            "Я понял команду «новый лист», но ещё не настроен топик-источник. "
            "Админу нужно указать CONTENT_SOURCE_THREAD_ID.",
        )
        return

    if not _is_source_topic(message):
        await _send_temporary_group_reply(
            bot,
            message,
            "Забираю новые листы только из топика «Проза и поэзия».",
        )
        return

    source_message = message.reply_to_message or message
    publication_text = extract_publication_text(
        source_message,
        remove_trigger=source_message.message_id == message.message_id,
    )
    if not publication_text:
        await _send_temporary_group_reply(
            bot,
            message,
            "Не вижу текста для публикации. Ответьте командой "
            "@DomListyevBot новый лист на сообщение со стихотворением "
            "или напишите текст после команды.",
        )
        return

    post_data = build_submission_data_from_message(source_message, text=publication_text)
    await _ask_creative_group(message, state, post_data, bot)


@router.message(ProposedPostSubmission.waiting_creative_group)
async def receive_creative_group(message: Message, state: FSMContext, bot: Bot) -> None:
    """Принять название творческой группы."""
    if await _reject_if_wrong_submitter_message(message, state):
        return
    if await _reject_if_expired_message(message, state, bot):
        return

    if not message.text:
        await _answer_and_remember(
            message,
            state,
            "Пришлите название творческой группы текстом или нажмите «Без творческой группы».",
            reply_markup=creative_group_keyboard,
        )
        return

    try:
        await _remember_user_cleanup_message(state, message)
        creative_group, creative_group_format = extract_creative_group_from_message(message)
        await _ask_author_visibility(
            message,
            state,
            creative_group=creative_group,
            creative_group_format=creative_group_format,
        )
    except RuntimeError:
        await _answer_and_remember(
            message,
            state,
            "Черновик предложки потерялся. Пожалуйста, начните заново.",
            reply_markup=restart_keyboard,
        )


@router.callback_query(F.data == "proposed_skip_creative_group")
async def skip_creative_group(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Обработать кнопку пропуска творческой группы."""
    if await state.get_state() != ProposedPostSubmission.waiting_creative_group.state:
        await callback.answer()
        return
    if await _reject_if_wrong_submitter_callback(callback, state):
        return
    if await _reject_if_expired_callback(callback, state, bot):
        return

    try:
        await _ask_author_visibility(callback.message, state, creative_group=None)
    except RuntimeError:
        await _answer_and_remember(
            callback.message,
            state,
            "Черновик предложки потерялся. Пожалуйста, начните заново.",
            reply_markup=restart_keyboard,
        )
        await callback.answer()
        return

    await callback.answer("Без творческой группы")


async def _finish_author_visibility_choice(
    message: Message,
    state: FSMContext,
    bot: Bot,
    *,
    publish_author: bool,
) -> None:
    """Завершить выбор автора и отправить лист на модерацию."""
    submission_data = await state.get_data()
    is_group_submission = bool(submission_data.get("cleanup_group_bot_messages"))
    try:
        post_id, cleanup_messages = await _finish_proposed_post_submission(
            bot=bot,
            state=state,
            publish_author=publish_author,
        )
    except RuntimeError:
        await message.answer(
            "Черновик предложки потерялся. Пожалуйста, начните заново.",
            reply_markup=restart_keyboard,
        )
        return

    await _delete_remembered_cleanup_messages(bot, cleanup_messages)
    await send_content(
        message,
        "propose_post_received",
        suffix=f"\n\nНомер листа: #{post_id}",
        reply_markup=None if is_group_submission else restart_keyboard,
    )


@router.callback_query(F.data.in_({"proposed_author_yes", "proposed_author_no"}))
async def receive_author_visibility_choice(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Принять выбор видимости автора кнопкой."""
    if await state.get_state() != ProposedPostSubmission.waiting_author_visibility.state:
        await callback.answer()
        return
    if await _reject_if_wrong_submitter_callback(callback, state):
        return
    if await _reject_if_expired_callback(callback, state, bot):
        return

    await _finish_author_visibility_choice(
        callback.message,
        state,
        bot,
        publish_author=callback.data == "proposed_author_yes",
    )
    await callback.answer()


@router.message(ProposedPostSubmission.waiting_author_visibility)
async def receive_author_visibility_text(message: Message, state: FSMContext, bot: Bot) -> None:
    """Принять выбор видимости автора текстом."""
    if await _reject_if_wrong_submitter_message(message, state):
        return
    if await _reject_if_expired_message(message, state, bot):
        return

    if not message.text:
        await _answer_and_remember(
            message,
            state,
            get_text("author_visibility_prompt"),
            reply_markup=author_visibility_keyboard,
        )
        return

    normalized = message.text.strip().lower()
    if normalized in AUTHOR_VISIBILITY_YES_VALUES:
        await _finish_author_visibility_choice(message, state, bot, publish_author=True)
        return
    if normalized in AUTHOR_VISIBILITY_NO_VALUES:
        await _finish_author_visibility_choice(message, state, bot, publish_author=False)
        return

    await _answer_and_remember(
        message,
        state,
        "Пожалуйста, выберите кнопкой или напишите: да / нет.",
        reply_markup=author_visibility_keyboard,
    )


# --- Админская модерация: одобрение, публикация, отклонение и правки --------

@router.callback_query(F.data.startswith("proposed_approve:"))
async def approve_new_leaf(callback: CallbackQuery, bot: Bot) -> None:
    """Админ одобряет лист и ставит его в очередь."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    post_id = callback_int_id(callback.data)
    scheduled_for = approve_proposed_post(post_id)
    if scheduled_for is None:
        await callback.answer("Не удалось одобрить: пост не найден или уже опубликован", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Одобрено")

    post = get_proposed_post(post_id)
    author_notified = False
    if post is not None:
        author_notified = await notify_author_about_approval(bot, post)

    notification_line = (
        "\nАвтору отправлено личное уведомление."
        if author_notified
        else "\nАвтору не удалось отправить личное уведомление."
    )
    await callback.message.answer(
        f"✅ Лист #{post_id} одобрен и поставлен в очередь на {format_scheduled_for(scheduled_for)}."
        f"{notification_line}",
    )


@router.callback_query(F.data.startswith("proposed_publish_now:"))
async def publish_new_leaf_now(callback: CallbackQuery, bot: Bot) -> None:
    """Админ публикует лист сразу, минуя очередь."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    post_id = callback_int_id(callback.data)
    message_id = await publish_proposed_post_now(bot, post_id)
    if message_id is None:
        await callback.answer("Пост не найден", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"🚀 Лист #{post_id} опубликован в канале.",
        reply_markup=restart_keyboard,
    )
    await callback.answer("Опубликовано")


@router.callback_query(F.data.startswith("proposed_reject:"))
async def reject_new_leaf(callback: CallbackQuery, bot: Bot) -> None:
    """Админ отклоняет лист и при необходимости архивирует его в топик."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    post_id = callback_int_id(callback.data)
    post = get_proposed_post(post_id)
    if post is None:
        await callback.answer("Пост не найден", show_alert=True)
        return

    if not reject_proposed_post(post_id):
        await callback.answer("Не удалось отклонить", show_alert=True)
        return

    if settings.ADMIN_REJECTS_THREAD_ID is not None:
        await send_rejected_post_to_archive(bot, post)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"❌ Лист #{post_id} отклонён.",
        reply_markup=restart_keyboard,
    )
    await callback.answer("Отклонено")


@router.callback_query(F.data.startswith("proposed_edit:"))
async def start_edit_new_leaf(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать текущий текст листа перед подтверждаемой правкой."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Только для администраторов", show_alert=True); return
    post_id=callback_int_id(callback.data); post=get_proposed_post(post_id)
    if post is None:
        await callback.answer("Пост не найден",show_alert=True); return
    await state.clear(); await state.update_data(post_id=post_id,old_value=post["text"])
    await state.set_state(ProposedPostModeration.waiting_edited_text)
    await callback.message.answer(f"Текущее значение:\n«{_edit_preview(post['text'], 3500)}»\n\nОтправьте новое значение.",reply_markup=edit_prompt_keyboard(f"proposed_edit_cancel:{post_id}")); await callback.answer()


@router.message(ProposedPostModeration.waiting_edited_text)
async def receive_edited_new_leaf(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id): return
    text=extract_publication_text(message)
    if not text:
        await message.answer("Пришлите новый текст обычным текстовым сообщением."); return
    data=await state.get_data(); post_id=int(data["post_id"])
    await state.update_data(pending_value=text); await state.set_state(ProposedPostModeration.confirming_edit)
    await message.answer(f"Было:\n«{_edit_preview(data['old_value'])}»\n\nСтанет:\n«{_edit_preview(text)}»",reply_markup=edit_confirm_keyboard(save_callback=f"proposed_edit_save:{post_id}",retry_callback=f"proposed_edit_retry:{post_id}",cancel_callback=f"proposed_edit_cancel:{post_id}"))


async def _return_to_proposed_card(message: Message, post_id: int, bot: Bot) -> None:
    post=get_proposed_post(post_id)
    if post:
        await send_stored_review_card(
            bot,
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            post=post,
        )


@router.callback_query(F.data.startswith("proposed_edit_save:"))
async def proposed_edit_save(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not is_admin(callback.from_user.id): return
    data=await state.get_data(); post_id=int(callback.data.split(":",1)[1]); text=data.get("pending_value")
    update_proposed_post_text(post_id,text,text_format="html"); post=get_proposed_post(post_id); await state.clear()
    if post and post["admin_chat_id"] and post["admin_message_id"]:
        try:
            await bot.edit_message_text(chat_id=post["admin_chat_id"],message_id=post["admin_message_id"],text=build_review_text_from_post(post),parse_mode=parse_mode_for_text_format(post["text_format"]),reply_markup=proposed_post_review_keyboard(post_id))
        except Exception: pass
    await callback.answer("Сохранено"); await _return_to_proposed_card(callback.message,post_id,bot)


@router.callback_query(F.data.startswith("proposed_edit_retry:"))
async def proposed_edit_retry(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    post_id=int(callback.data.split(":",1)[1]); data=await state.get_data(); await state.set_state(ProposedPostModeration.waiting_edited_text)
    await callback.message.answer(f"Текущее значение:\n«{_edit_preview(data.get('old_value',''), 3500)}»\n\nОтправьте новое значение.",reply_markup=edit_prompt_keyboard(f"proposed_edit_cancel:{post_id}")); await callback.answer()


@router.callback_query(F.data.startswith("proposed_edit_cancel:"))
async def proposed_edit_cancel(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not is_admin(callback.from_user.id): return
    post_id=int(callback.data.split(":",1)[1]); await state.clear(); await callback.answer("Изменения отменены")
    await _return_to_proposed_card(callback.message,post_id,bot)
