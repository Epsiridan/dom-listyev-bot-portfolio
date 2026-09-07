# -*- coding: utf-8 -*-
"""Универсальная подача работ на конкурсы."""

from html import escape as html_escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import settings
from handlers.screens import safe_edit_or_answer
from keyboards import (
    ai_keyboard,
    contest_back_keyboard,
    contest_info_keyboard,
    contest_subscription_keyboard,
    finish_text_keyboard,
    restart_keyboard,
    submission_review_keyboard,
    work_format_keyboard,
)
from services.contest_database import (
    count_user_contest_submissions,
    get_contest,
    get_contest_by_external_key,
    save_contest_submission,
)
from services.contests import (
    ECHO_EXTERNAL_KEY,
    allowed_categories,
    build_contest_info_html,
    build_criteria_html,
    contest_timing_status,
    contest_unavailable_text,
    format_allowed_categories,
    message_matches_allowed_file,
    missing_user_subscriptions,
    send_submission_to_destination,
)
from states import ContestSubmission
from texts import ADMIN_TRANSFER_ERROR_TEXT
from services.content import get_text

router = Router()


def _echo_contest():
    return get_contest_by_external_key(ECHO_EXTERNAL_KEY)


def _contest_id_from_data(value: str | None) -> int | None:
    if not value:
        return None
    tail = value.rsplit(":", maxsplit=1)[-1]
    return int(tail) if tail.isdigit() else None


async def _contest_for_callback(callback: CallbackQuery, state: FSMContext | None = None):
    contest_id = _contest_id_from_data(callback.data)
    if contest_id is None and state is not None:
        data = await state.get_data()
        contest_id = data.get("contest_id")
    if contest_id is not None:
        return get_contest(int(contest_id))
    return _echo_contest()


def _open_for_user(contest, user_id: int) -> bool:
    timing = contest_timing_status(contest)
    return timing == "open" or (timing == "upcoming" and user_id in settings.ADMIN_IDS)


def _limit_reached(contest, user_id: int) -> bool:
    limit = contest["max_submissions"]
    if limit is None:
        return False
    return count_user_contest_submissions(int(contest["id"]), user_id) >= int(limit)


def _limit_text(contest) -> str:
    limit = contest["max_submissions"]
    if limit == 1:
        return "Вы уже отправили работу на этот конкурс. По условиям можно подать только одну работу."
    return f"Вы уже отправили максимально допустимое число работ: {limit}."


async def _show_unavailable(callback: CallbackQuery, contest) -> None:
    await safe_edit_or_answer(
        callback,
        contest_unavailable_text(contest),
        reply_markup=restart_keyboard,
    )


async def _show_subscription_prompt(callback: CallbackQuery, contest, missing) -> None:
    names = "\n".join(f"• {row['title']}" for row in missing)
    await safe_edit_or_answer(
        callback,
        get_text("contest_subscription_required").replace("{channels}", names),
        reply_markup=contest_subscription_keyboard(int(contest["id"]), missing),
    )


async def _start_form(callback: CallbackQuery, state: FSMContext, contest) -> None:
    await state.clear()
    await state.update_data(contest_id=int(contest["id"]))
    await state.set_state(ContestSubmission.waiting_author)
    await safe_edit_or_answer(
        callback,
        "Как подписать вашу работу?\n\nНапишите имя, псевдоним или название Telegram-канала.",
    )


async def _show_review_message(message: Message, state: FSMContext, contest) -> None:
    await state.set_state(ContestSubmission.reviewing_info)
    data = await state.get_data()
    lines = [
        "<b>Проверьте данные заявки:</b>",
        "",
        f"Имя / псевдоним: {html_escape(data.get('author', '—'))}",
        f"Название работы: {html_escape(data.get('title', '—'))}",
    ]
    if contest["require_repost"]:
        lines.append(f"Ссылка на репост: {html_escape(data.get('repost_link', '—'))}")
    if contest["ask_ai"]:
        lines.append(f"ИИ: {html_escape(data.get('ai_link') or 'не использовался')}")
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=submission_review_keyboard(int(contest["id"])),
    )


async def _show_review_callback(callback: CallbackQuery, state: FSMContext, contest) -> None:
    await state.set_state(ContestSubmission.reviewing_info)
    data = await state.get_data()
    lines = [
        "<b>Проверьте данные заявки:</b>",
        "",
        f"Имя / псевдоним: {html_escape(data.get('author', '—'))}",
        f"Название работы: {html_escape(data.get('title', '—'))}",
    ]
    if contest["require_repost"]:
        lines.append(f"Ссылка на репост: {html_escape(data.get('repost_link', '—'))}")
    if contest["ask_ai"]:
        lines.append(f"ИИ: {html_escape(data.get('ai_link') or 'не использовался')}")
    await safe_edit_or_answer(
        callback,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=submission_review_keyboard(int(contest["id"])),
    )


async def _after_title(message: Message, state: FSMContext, contest) -> None:
    if contest["require_repost"]:
        await state.set_state(ContestSubmission.waiting_repost)
        await message.answer("Пришлите ссылку на репост анонса конкурса.")
    elif contest["ask_ai"]:
        await state.set_state(ContestSubmission.waiting_ai_choice)
        await message.answer("Использовался ли ИИ при создании работы?", reply_markup=ai_keyboard)
    else:
        await _show_review_message(message, state, contest)


async def _after_repost(message: Message, state: FSMContext, contest) -> None:
    if contest["ask_ai"]:
        await state.set_state(ContestSubmission.waiting_ai_choice)
        await message.answer("Использовался ли ИИ при создании работы?", reply_markup=ai_keyboard)
    else:
        await _show_review_message(message, state, contest)


async def _checks_before_submission(bot: Bot, contest, user_id: int) -> tuple[bool, list]:
    if not _open_for_user(contest, user_id) or _limit_reached(contest, user_id):
        return False, []
    missing = await missing_user_subscriptions(bot, int(contest["id"]), user_id)
    return not missing, missing


async def _finish_submission(
    *, bot: Bot, contest, user, data: dict, submission_format: str,
    source_messages: list[tuple[int, int]], state: FSMContext,
    answer_target: Message,
) -> bool:
    try:
        await send_submission_to_destination(
            bot,
            contest=contest,
            user=user,
            data=data,
            submission_format=submission_format,
            source_messages=source_messages,
        )
    except Exception:
        await answer_target.answer(ADMIN_TRANSFER_ERROR_TEXT, reply_markup=restart_keyboard)
        return False
    save_contest_submission(
        contest_id=int(contest["id"]),
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        author=data.get("author", ""),
        title=data.get("title", ""),
        repost_link=data.get("repost_link"),
        ai_link=data.get("ai_link"),
        submission_format=submission_format,
    )
    await state.clear()
    try:
        await answer_target.answer(
            contest["success_message_html"],
            parse_mode="HTML",
            reply_markup=restart_keyboard,
        )
    except TelegramBadRequest:
        await answer_target.answer(contest["success_message_html"], reply_markup=restart_keyboard)
    return True


@router.callback_query(F.data == "contest_info")
@router.callback_query(F.data.startswith("contest_info:"))
async def contest_info(callback: CallbackQuery, state: FSMContext) -> None:
    contest = await _contest_for_callback(callback, state)
    if contest is None or contest_timing_status(contest) == "closed":
        await _show_unavailable(callback, contest)
        await callback.answer()
        return
    await state.clear()
    await safe_edit_or_answer(
        callback,
        build_contest_info_html(contest),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=contest_info_keyboard(
            int(contest["id"]),
            has_criteria=bool(contest["criteria_html"]),
            show_rules=bool(contest["show_community_rules"]),
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("contest_criteria:"))
async def contest_criteria(callback: CallbackQuery) -> None:
    contest = get_contest(_contest_id_from_data(callback.data) or 0)
    if contest is None:
        await callback.answer("Конкурс не найден.", show_alert=True)
        return
    await safe_edit_or_answer(
        callback,
        build_criteria_html(contest),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=contest_back_keyboard(int(contest["id"])),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("contest_rules:"))
async def contest_rules(callback: CallbackQuery) -> None:
    contest_id = _contest_id_from_data(callback.data) or 0
    contest = get_contest(contest_id)
    if contest is None or not contest["show_community_rules"]:
        await callback.answer("Правила для этого конкурса не показываются.", show_alert=True)
        return
    await safe_edit_or_answer(callback, get_text("community_rules"), reply_markup=contest_back_keyboard(contest_id))
    await callback.answer()


@router.callback_query(F.data == "contest_apply")
@router.callback_query(F.data.startswith("contest_apply:"))
async def contest_apply(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    contest = await _contest_for_callback(callback, state)
    if contest is None or not _open_for_user(contest, callback.from_user.id):
        await _show_unavailable(callback, contest)
        await callback.answer()
        return
    if _limit_reached(contest, callback.from_user.id):
        await safe_edit_or_answer(callback, _limit_text(contest), reply_markup=restart_keyboard)
        await callback.answer()
        return
    missing = await missing_user_subscriptions(bot, int(contest["id"]), callback.from_user.id)
    if missing:
        await state.clear()
        await state.update_data(contest_id=int(contest["id"]), subscription_resume="start")
        await state.set_state(ContestSubmission.waiting_subscription)
        await _show_subscription_prompt(callback, contest, missing)
        await callback.answer()
        return
    await _start_form(callback, state, contest)
    await callback.answer()


@router.callback_query(F.data == "check_contest_subscription")
@router.callback_query(F.data.startswith("contest_sub_check:"))
async def subscription_recheck(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    contest = await _contest_for_callback(callback, state)
    if contest is None or not _open_for_user(contest, callback.from_user.id):
        await _show_unavailable(callback, contest)
        await callback.answer()
        return
    missing = await missing_user_subscriptions(bot, int(contest["id"]), callback.from_user.id)
    if missing:
        await _show_subscription_prompt(callback, contest, missing)
        await callback.answer("Пока не вижу все подписки.", show_alert=True)
        return
    data = await state.get_data()
    resume = data.get("subscription_resume", "start")
    if resume == "format":
        await state.set_state(ContestSubmission.waiting_format)
        await safe_edit_or_answer(
            callback,
            "Подписки найдены. Как вы хотите отправить работу?",
            reply_markup=work_format_keyboard(int(contest["id"]), contest["submission_mode"]),
        )
    elif resume == "finish_text":
        await state.set_state(ContestSubmission.waiting_text_work)
        await safe_edit_or_answer(
            callback,
            "Подписки найдены. Теперь можно завершить отправку текста.",
            reply_markup=finish_text_keyboard(int(contest["id"])),
        )
    elif resume == "file":
        await state.set_state(ContestSubmission.waiting_file_work)
        await safe_edit_or_answer(callback, "Подписки найдены. Отправьте файл ещё раз.")
    else:
        await _start_form(callback, state, contest)
    await callback.answer("Подписки найдены.")


@router.message(ContestSubmission.waiting_author)
async def author_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Отправьте имя или псевдоним обычным текстом.")
        return
    if len(message.text.strip()) > 200:
        await message.answer("Имя слишком длинное. Максимум 200 символов.")
        return
    await state.update_data(author=message.text.strip())
    await state.set_state(ContestSubmission.waiting_title)
    await message.answer("Введите название работы. Если его нет, напишите: «Без названия».")


@router.message(ContestSubmission.waiting_title)
async def title_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Отправьте название обычным текстом.")
        return
    if len(message.text.strip()) > 300:
        await message.answer("Название слишком длинное. Максимум 300 символов.")
        return
    await state.update_data(title=message.text.strip())
    data = await state.get_data()
    contest = get_contest(int(data["contest_id"]))
    await _after_title(message, state, contest)


@router.message(ContestSubmission.waiting_repost)
async def repost_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Отправьте ссылку обычным текстом.")
        return
    await state.update_data(repost_link=message.text.strip())
    data = await state.get_data()
    contest = get_contest(int(data["contest_id"]))
    await _after_repost(message, state, contest)


@router.callback_query(F.data.in_({"ai_used_yes", "ai_used_no", "contest_ai:yes", "contest_ai:no"}))
async def ai_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != ContestSubmission.waiting_ai_choice.state:
        await callback.answer()
        return
    yes = callback.data in {"ai_used_yes", "contest_ai:yes"}
    if yes:
        await state.set_state(ContestSubmission.waiting_ai_link)
        await safe_edit_or_answer(callback, "Пришлите ссылку на диалог с ИИ, в котором велась работа.")
    else:
        await state.update_data(ai_link=None)
        data = await state.get_data()
        contest = get_contest(int(data["contest_id"]))
        await _show_review_callback(callback, state, contest)
    await callback.answer()


@router.message(ContestSubmission.waiting_ai_link)
async def ai_link_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пришлите ссылку обычным текстом.")
        return
    await state.update_data(ai_link=message.text.strip())
    data = await state.get_data()
    contest = get_contest(int(data["contest_id"]))
    await _show_review_message(message, state, contest)


@router.callback_query(F.data.startswith("contest_restart:"))
async def restart_form(callback: CallbackQuery, state: FSMContext) -> None:
    contest = await _contest_for_callback(callback, state)
    if contest is None:
        await callback.answer("Конкурс не найден.", show_alert=True)
        return
    await _start_form(callback, state, contest)
    await callback.answer()


@router.callback_query(F.data == "confirm_submission_info")
@router.callback_query(F.data.startswith("contest_confirm:"))
async def confirm_info(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if await state.get_state() != ContestSubmission.reviewing_info.state:
        await safe_edit_or_answer(
            callback,
            "Черновик заявки уже сброшен. Откройте конкурс из главного меню и заполните форму заново.",
            reply_markup=restart_keyboard,
        )
        await callback.answer()
        return
    contest = await _contest_for_callback(callback, state)
    if contest is None or not _open_for_user(contest, callback.from_user.id):
        await _show_unavailable(callback, contest)
        await callback.answer()
        return
    if _limit_reached(contest, callback.from_user.id):
        await safe_edit_or_answer(callback, _limit_text(contest), reply_markup=restart_keyboard)
        await callback.answer()
        return
    missing = await missing_user_subscriptions(bot, int(contest["id"]), callback.from_user.id)
    if missing:
        await state.update_data(subscription_resume="format")
        await state.set_state(ContestSubmission.waiting_subscription)
        await _show_subscription_prompt(callback, contest, missing)
        await callback.answer()
        return
    await state.set_state(ContestSubmission.waiting_format)
    await safe_edit_or_answer(
        callback,
        "Как вы хотите отправить работу?",
        reply_markup=work_format_keyboard(int(contest["id"]), contest["submission_mode"]),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"format_text", "format_file"}))
@router.callback_query(F.data.startswith("contest_format:"))
async def format_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != ContestSubmission.waiting_format.state:
        await callback.answer("Этот шаг формы уже неактивен.", show_alert=True)
        return
    contest = await _contest_for_callback(callback, state)
    if contest is None or not _open_for_user(contest, callback.from_user.id):
        await _show_unavailable(callback, contest)
        await callback.answer()
        return
    is_text = callback.data == "format_text" or callback.data.startswith("contest_format:text:")
    if is_text:
        if contest["submission_mode"] not in {"text", "both"}:
            await callback.answer("Этот конкурс не принимает текст в сообщении.", show_alert=True)
            return
        await state.update_data(text_messages=[])
        await state.set_state(ContestSubmission.waiting_text_work)
        await safe_edit_or_answer(
            callback,
            "Отправьте текст одним или несколькими сообщениями. Telegram-форматирование сохранится.\n\nКогда закончите, нажмите «✅ Завершить отправку».",
            reply_markup=finish_text_keyboard(int(contest["id"])),
        )
    else:
        if contest["submission_mode"] not in {"files", "both"}:
            await callback.answer("Этот конкурс не принимает файлы.", show_alert=True)
            return
        await state.set_state(ContestSubmission.waiting_file_work)
        categories = allowed_categories(contest)
        await safe_edit_or_answer(
            callback,
            "Отправьте файл или медиа.\n\nДопустимые типы:\n"
            + format_allowed_categories(categories),
        )
    await callback.answer()


@router.message(ContestSubmission.waiting_text_work)
async def text_part_received(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("В этом режиме нужно отправить текстовое сообщение.")
        return
    data = await state.get_data()
    messages = list(data.get("text_messages", []))
    messages.append([message.chat.id, message.message_id])
    await state.update_data(text_messages=messages)
    await message.answer(
        f"Получил часть {len(messages)}.",
        reply_markup=finish_text_keyboard(int(data["contest_id"])),
    )


@router.callback_query(F.data == "finish_text_submission")
@router.callback_query(F.data.startswith("contest_finish_text:"))
async def finish_text(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if await state.get_state() != ContestSubmission.waiting_text_work.state:
        await callback.answer("Этот шаг формы уже неактивен.", show_alert=True)
        return
    data = await state.get_data()
    contest = await _contest_for_callback(callback, state)
    if contest is None or not data.get("text_messages"):
        await callback.answer("Сначала отправьте хотя бы одну часть текста.", show_alert=True)
        return
    ok, missing = await _checks_before_submission(bot, contest, callback.from_user.id)
    if not ok:
        if missing:
            await state.update_data(subscription_resume="finish_text")
            await state.set_state(ContestSubmission.waiting_subscription)
            await _show_subscription_prompt(callback, contest, missing)
        elif _limit_reached(contest, callback.from_user.id):
            await safe_edit_or_answer(callback, _limit_text(contest), reply_markup=restart_keyboard)
        else:
            await _show_unavailable(callback, contest)
        await callback.answer()
        return
    source_messages = [(int(item[0]), int(item[1])) for item in data["text_messages"]]
    await _finish_submission(
        bot=bot,
        contest=contest,
        user=callback.from_user,
        data=data,
        submission_format="текст",
        source_messages=source_messages,
        state=state,
        answer_target=callback.message,
    )
    await callback.answer()


@router.message(ContestSubmission.waiting_file_work)
async def file_received(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    contest = get_contest(int(data["contest_id"]))
    categories = allowed_categories(contest)
    if not message_matches_allowed_file(message, categories):
        await message.answer(
            "Этот тип файла не принимается.\n\nДопустимые типы:\n"
            + format_allowed_categories(categories)
        )
        return
    ok, missing = await _checks_before_submission(bot, contest, message.from_user.id)
    if not ok:
        if missing:
            await state.update_data(subscription_resume="file")
            await state.set_state(ContestSubmission.waiting_subscription)
            names = "\n".join(f"• {row['title']}" for row in missing)
            await message.answer(
                f"Сначала подпишитесь на:\n{names}",
                reply_markup=contest_subscription_keyboard(int(contest["id"]), missing),
            )
        elif _limit_reached(contest, message.from_user.id):
            await message.answer(_limit_text(contest), reply_markup=restart_keyboard)
        else:
            await message.answer(contest_unavailable_text(contest), reply_markup=restart_keyboard)
        return
    await _finish_submission(
        bot=bot,
        contest=contest,
        user=message.from_user,
        data=data,
        submission_format="файл / медиа",
        source_messages=[(message.chat.id, message.message_id)],
        state=state,
        answer_target=message,
    )
