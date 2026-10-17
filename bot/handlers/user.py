"""User panel: choose a category, answer questions, check the answer with AI or see the reference."""

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.grader import Grader, format_grade
from bot.storage import Question, Storage
from bot.texts import titled_chunks

log = logging.getLogger(__name__)


class Practice(StatesGroup):
    answering = State()


def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def _next_kb(category_id: int, with_check: bool = False) -> InlineKeyboardMarkup:
    rows = [[("🤖 Проверить ИИ", "u:check")]] if with_check else []
    rows += [[("➡️ Следующий вопрос", f"u:next:{category_id}")], [("📚 Сменить категорию", "u:cats")]]
    return _kb(*rows)


async def send_categories(message: Message, storage: Storage) -> None:
    categories = storage.list_practice_categories()
    if not categories:
        await message.answer("Вопросов пока нет. Загляните позже!")
        return
    await message.answer(
        "Выберите категорию:",
        reply_markup=_kb(*[[(f"{c.name} ({c.answered})", f"u:cat:{c.id}")] for c in categories]),
    )


async def _send_question(message: Message, state: FSMContext, storage: Storage, user_id: int, category_id: int, exclude_id: int | None = None) -> None:
    q = storage.next_question(user_id, category_id, exclude_id=exclude_id)
    if q is None:
        await state.clear()
        await message.answer("В этой категории пока нет вопросов.", reply_markup=_kb([("📚 Сменить категорию", "u:cats")]))
        return
    await state.set_state(Practice.answering)
    await state.set_data({"category_id": category_id, "question_id": q.id, "answer": None})
    await message.answer(
        f"<b>{escape(q.category_name)}</b>\n\n❓ {escape(q.text)}\n\n"
        "<i>Напишите ответ сообщением, а потом проверьте его ИИ. Или сразу посмотрите эталон.</i>",
        reply_markup=_kb(
            [("📖 Показать эталон", f"u:ref:{q.id}")],
            [("⏭ Пропустить", f"u:next:{category_id}"), ("📚 Сменить категорию", "u:cats")],
        ),
    )


async def _send_reference(message: Message, q: Question, markup: InlineKeyboardMarkup) -> None:
    chunks = titled_chunks("<b>📖 Эталонный ответ</b>", q.answer or "")
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=markup)


async def _question_gone(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Этот вопрос удалён администратором.", reply_markup=_kb([("📚 Выбрать категорию", "u:cats")]))


async def on_categories(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    await callback.answer()
    await send_categories(callback.message, storage)


async def on_category(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await callback.answer()
    await _send_question(callback.message, state, storage, callback.from_user.id, int(callback.data.split(":")[2]))


async def on_next(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await callback.answer()
    data = await state.get_data()
    await _send_question(callback.message, state, storage, callback.from_user.id, int(callback.data.split(":")[2]), exclude_id=data.get("question_id"))


async def on_reference(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await callback.answer()
    q = storage.get_question(int(callback.data.split(":")[2]))
    if q is None or not q.answer:
        await _question_gone(callback.message, state)
        return
    storage.record_attempt(callback.from_user.id, q.id, "reference")
    data = await state.get_data()
    has_answer = data.get("question_id") == q.id and bool(data.get("answer"))
    await _send_reference(callback.message, q, _next_kb(q.category_id, with_check=has_answer))


async def on_check(callback: CallbackQuery, state: FSMContext, storage: Storage, grader: Grader, bot: Bot) -> None:
    await callback.answer()
    data = await state.get_data()
    if not data.get("answer"):
        await callback.message.answer("Сначала напишите ответ на текущий вопрос сообщением.")
        return
    q = storage.get_question(data["question_id"])
    if q is None or not q.answer:
        await _question_gone(callback.message, state)
        return
    await callback.message.answer("⏳ Проверяю ответ…")
    await bot.send_chat_action(callback.message.chat.id, ChatAction.TYPING)
    try:
        grade = await grader.grade(q.text, q.answer, data["answer"])
    except Exception:
        log.exception("Grading failed")
        await callback.message.answer("Не получилось проверить ответ, попробуйте ещё раз.", reply_markup=_next_kb(q.category_id, with_check=True))
        return
    storage.record_attempt(callback.from_user.id, q.id, "ai", score=grade.score)
    await callback.message.answer(format_grade(grade))
    await _send_reference(callback.message, q, _next_kb(q.category_id))


async def on_answer(message: Message, state: FSMContext, storage: Storage) -> None:
    data = await state.get_data()
    q = storage.get_question(data["question_id"])
    if q is None or not q.answer:
        await _question_gone(message, state)
        return
    await state.update_data(answer=message.text)
    await message.answer(
        "Ответ записан. Можно проверить его ИИ или сравнить с эталоном самостоятельно. "
        "Чтобы исправить ответ, просто отправьте новый.",
        reply_markup=_kb(
            [("🤖 Проверить ИИ", "u:check"), ("📖 Показать эталон", f"u:ref:{q.id}")],
            [("➡️ Следующий вопрос", f"u:next:{q.category_id}")],
        ),
    )


async def on_non_text_answer(message: Message) -> None:
    await message.answer("Пока я понимаю только текстовые ответы.")


async def on_admin_button_denied(callback: CallbackQuery) -> None:
    await callback.answer("Нет доступа", show_alert=True)


async def fallback(message: Message) -> None:
    await message.answer("Чтобы начать тренировку, выберите категорию: /start")


def create_router() -> Router:
    router = Router(name="user")
    router.callback_query.register(on_categories, F.data == "u:cats")
    router.callback_query.register(on_category, F.data.startswith("u:cat:"))
    router.callback_query.register(on_next, F.data.startswith("u:next:"))
    router.callback_query.register(on_reference, F.data.startswith("u:ref:"))
    router.callback_query.register(on_check, F.data == "u:check")
    router.message.register(on_answer, Practice.answering, F.text)
    router.message.register(on_non_text_answer, Practice.answering)
    router.callback_query.register(on_admin_button_denied, F.data.startswith("a:"))
    router.message.register(fallback)
    return router
