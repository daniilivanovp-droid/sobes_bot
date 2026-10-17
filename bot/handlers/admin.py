"""Admin panel: categories, questions, reference answers, bulk import and usage stats.

Access is limited to Telegram user IDs from ADMIN_IDS: Telegram guarantees the sender's ID,
so unlike a password it cannot be guessed, leaked or brute-forced.
"""

from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.parsing import parse_question_blocks
from bot.storage import Storage
from bot.texts import TELEGRAM_LIMIT, short, split_text

PAGE_SIZE = 10
DEFAULT_CATEGORY = "Общее"
MENU_TEXT = "<b>Панель администратора</b>\nЧто будем делать?"
IMPORT_HELP = (
    "Отправьте вопросы сообщением или файлом .txt / .md (формат тот же, что на сайте «Собес.Тренер»).\n\n"
    "Вопросы разделяются строкой <code>---</code>. Первая строка блока — вопрос, остальное — эталонный ответ "
    "(можно не указывать и добавить позже). Строка <code># Категория</code> задаёт категорию для этого и следующих вопросов.\n\n"
    "<pre># Spark\nЧто такое RDD?\nНеизменяемая распределённая коллекция...\n---\nЧто такое shuffle?\n"
    "Перераспределение данных между партициями...\n---\n# Airflow\nЧто такое DAG?\nГраф задач...</pre>\n"
    "Вопросы без категории попадут в «Общее». /cancel — отмена."
)


class AdminInput(StatesGroup):
    category_name = State()
    question_text = State()
    question_answer = State()
    import_bank = State()
    set_answer = State()


def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def menu_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("➕ Добавить категорию", "a:newcat"), ("➕ Добавить вопрос", "a:addq")],
        [("📥 Импорт списком", "a:import")],
        [("📚 Вопросы и ответы", "a:browse")],
        [("📊 Статистика", "a:stats")],
    )


_BACK = ("← Меню", "a:menu")


async def _show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Replaces the message the button was on; long texts go out as new messages."""
    await callback.answer()
    if len(text) <= TELEGRAM_LIMIT:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass  # e.g. the message is too old or unchanged
        await callback.message.answer(text, reply_markup=markup)
        return
    chunks = split_text(text, TELEGRAM_LIMIT - 100)
    for chunk in chunks[:-1]:
        await callback.message.answer(chunk)
    await callback.message.answer(chunks[-1], reply_markup=markup)


def _categories_kb(storage: Storage, action: str) -> list[list[tuple[str, str]]]:
    return [[(f"{c.name} ({c.answered}/{c.questions})", f"{action}:{c.id}")] for c in storage.list_categories()]


def _category_page(storage: Storage, category_id: int, page: int) -> tuple[str, InlineKeyboardMarkup] | None:
    category = storage.get_category(category_id)
    if category is None:
        return None
    questions = storage.list_questions(category_id)
    pages = max(1, -(-len(questions) // PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    rows = [[(("✅ " if q.answer else "⚪️ ") + short(q.text), f"a:q:{q.id}")] for q in questions[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(("◀", f"a:cat:{category_id}:{page - 1}"))
        nav.append((f"{page + 1}/{pages}", f"a:cat:{category_id}:{page}"))
        if page < pages - 1:
            nav.append(("▶", f"a:cat:{category_id}:{page + 1}"))
        rows.append(nav)
    rows += [
        [("➕ Добавить вопрос", f"a:addq:{category_id}")],
        [("🗑 Удалить категорию", f"a:delcat:{category_id}")],
        [("← Категории", "a:browse"), _BACK],
    ]
    text = (
        f"<b>{escape(category.name)}</b>: вопросов {category.questions}, с эталоном {category.answered}.\n"
        "✅ — есть эталонный ответ, ⚪️ — нет (такие вопросы пользователи не видят)."
    )
    return text, _kb(*rows)


def _question_card(storage: Storage, question_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    q = storage.get_question(question_id)
    if q is None:
        return None
    answer = f"<b>Эталонный ответ:</b>\n{escape(q.answer)}" if q.answer else "<i>Эталонный ответ не задан.</i>"
    text = f"<b>{escape(q.category_name)}</b> · вопрос #{q.id}\n\n❓ {escape(q.text)}\n\n{answer}"
    return text, _kb(
        [("✏️ Изменить ответ" if q.answer else "✏️ Задать ответ", f"a:ans:{q.id}")],
        [("🗑 Удалить вопрос", f"a:delq:{q.id}")],
        [("← К списку", f"a:cat:{q.category_id}:0"), _BACK],
    )


def _format_stats(storage: Storage) -> str:
    s = storage.stats()

    def avg(v):
        return f"{v:.1f}" if v is not None else "—"

    lines = [
        "<b>📊 Статистика</b>",
        f"Пользователей: {s.users_total} (новых за 7 дней: {s.users_new_7d})",
        f"Активных за сутки: {s.users_active_1d}, за 7 дней: {s.users_active_7d}",
        f"Вопросов в базе: {s.questions_total} (с эталоном: {s.questions_answered})",
        "",
        f"Всего ответов: {s.attempts_total}",
        f"Проверок ИИ: {s.ai_checks}",
        f"Просмотров эталона: {s.reference_views}",
        f"Средняя оценка ИИ: {avg(s.avg_score)}",
    ]
    if s.by_category:
        lines += ["", "<b>По категориям</b>"]
        lines += [f"• {escape(c.name)}: {c.attempts} (ср. оценка {avg(c.avg_score)})" for c in s.by_category]
    if s.top_users:
        lines += ["", "<b>Самые активные</b>"]
        lines += [f"• {escape(u.display_name)}: {u.attempts} (ср. оценка {avg(u.avg_score)})" for u in s.top_users]
    return "\n".join(lines)


def create_router(admin_ids: frozenset[int]) -> Router:
    router = Router(name="admin")
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))

    @router.callback_query(F.data == "a:menu")
    async def on_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await _show(callback, MENU_TEXT, menu_kb())

    @router.callback_query(F.data == "a:stats")
    async def on_stats(callback: CallbackQuery, storage: Storage) -> None:
        await _show(callback, _format_stats(storage), _kb([_BACK]))

    # --- categories -----------------------------------------------------

    @router.callback_query(F.data == "a:newcat")
    async def on_new_category(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(AdminInput.category_name)
        await _show(callback, "Отправьте название новой категории, например <i>Spark</i>. /cancel — отмена.")

    @router.message(AdminInput.category_name, F.text)
    async def on_category_name(message: Message, state: FSMContext, storage: Storage) -> None:
        name = message.text.strip()
        category = storage.add_category(name)
        if category is None:
            await message.answer(f"Категория «{escape(name)}» уже есть. Отправьте другое название или /cancel.")
            return
        await state.clear()
        await message.answer(
            f"✅ Категория «{escape(category.name)}» добавлена.",
            reply_markup=_kb([("➕ Добавить в неё вопрос", f"a:addq:{category.id}")], [_BACK]),
        )

    # --- adding questions -------------------------------------------------

    @router.callback_query(F.data == "a:addq")
    async def on_add_question(callback: CallbackQuery, storage: Storage) -> None:
        rows = _categories_kb(storage, "a:addq")
        if not rows:
            await _show(callback, "Сначала добавьте категорию.", _kb([("➕ Добавить категорию", "a:newcat")], [_BACK]))
            return
        await _show(callback, "В какую категорию добавить вопрос?", _kb(*rows, [("➕ Новая категория", "a:newcat")], [_BACK]))

    @router.callback_query(F.data.startswith("a:addq:"))
    async def on_add_question_to(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
        category = storage.get_category(int(callback.data.split(":")[2]))
        if category is None:
            await _show(callback, "Категория не найдена.", _kb([_BACK]))
            return
        await state.set_state(AdminInput.question_text)
        await state.set_data({"category_id": category.id})
        await _show(callback, f"Категория «{escape(category.name)}». Отправьте текст вопроса. /cancel — отмена.")

    @router.message(AdminInput.question_text, F.text)
    async def on_question_text(message: Message, state: FSMContext) -> None:
        await state.update_data(text=message.text)
        await state.set_state(AdminInput.question_answer)
        await message.answer("Теперь отправьте эталонный ответ. Или /skip, чтобы добавить его позже.")

    @router.message(AdminInput.question_answer, F.text)
    async def on_question_answer(message: Message, state: FSMContext, storage: Storage) -> None:
        data = await state.get_data()
        answer = None if message.text.strip() == "/skip" else message.text
        await state.clear()
        if storage.get_category(data["category_id"]) is None:
            await message.answer("Категория была удалена, вопрос не сохранён.", reply_markup=menu_kb())
            return
        q = storage.add_question(data["category_id"], data["text"], answer)
        note = "" if answer else " Эталонного ответа пока нет, пользователи увидят вопрос после того, как вы его добавите."
        await message.answer(
            f"✅ Вопрос добавлен в «{escape(q.category_name)}».{note}",
            reply_markup=_kb([("➕ Ещё вопрос сюда", f"a:addq:{q.category_id}")], [_BACK]),
        )

    # --- import -----------------------------------------------------------

    @router.callback_query(F.data == "a:import")
    async def on_import(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(AdminInput.import_bank)
        await _show(callback, IMPORT_HELP)

    @router.message(AdminInput.import_bank, F.text | F.document)
    async def on_import_data(message: Message, state: FSMContext, storage: Storage, bot: Bot) -> None:
        if message.document:
            raw = (await bot.download(message.document)).read().decode("utf-8-sig", errors="replace")
        else:
            raw = message.text
        parsed = parse_question_blocks(raw)
        if not parsed:
            await message.answer("Не нашёл ни одного вопроса. Проверьте формат и отправьте ещё раз, или /cancel.")
            return
        categories: dict[str, int] = {}
        for p in parsed:
            name = p.category or DEFAULT_CATEGORY
            if name not in categories:
                categories[name] = storage.get_or_create_category(name).id
            storage.add_question(categories[name], p.text, p.answer)
        await state.clear()
        with_answer = sum(1 for p in parsed if p.answer)
        await message.answer(
            f"✅ Импортировано вопросов: {len(parsed)} (с эталоном: {with_answer}).\n"
            f"Категории: {escape(', '.join(categories))}.",
            reply_markup=menu_kb(),
        )

    # --- browsing, answers, deletion ---------------------------------------

    @router.callback_query(F.data == "a:browse")
    async def on_browse(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
        await state.clear()
        rows = _categories_kb(storage, "a:cat")
        if not rows:
            await _show(callback, "Категорий пока нет.", _kb([("➕ Добавить категорию", "a:newcat")], [_BACK]))
            return
        await _show(callback, "Категории (с эталоном / всего вопросов):", _kb(*[[(t, d + ":0")] for [(t, d)] in rows], [_BACK]))

    @router.callback_query(F.data.startswith("a:cat:"))
    async def on_category(callback: CallbackQuery, storage: Storage) -> None:
        _, _, category_id, page = callback.data.split(":")
        view = _category_page(storage, int(category_id), int(page))
        await _show(callback, *(view or ("Категория не найдена.", _kb([_BACK]))))

    @router.callback_query(F.data.startswith("a:q:"))
    async def on_question(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
        await state.clear()
        view = _question_card(storage, int(callback.data.split(":")[2]))
        await _show(callback, *(view or ("Вопрос не найден.", _kb([_BACK]))))

    @router.callback_query(F.data.startswith("a:ans:"))
    async def on_set_answer(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(AdminInput.set_answer)
        await state.set_data({"question_id": int(callback.data.split(":")[2])})
        await callback.answer()
        await callback.message.answer("Отправьте эталонный ответ на этот вопрос. /cancel — отмена.")

    @router.message(AdminInput.set_answer, F.text)
    async def on_answer_text(message: Message, state: FSMContext, storage: Storage) -> None:
        data = await state.get_data()
        await state.clear()
        if not storage.set_answer(data["question_id"], message.text):
            await message.answer("Вопрос не найден, возможно его удалили.", reply_markup=menu_kb())
            return
        text, markup = _question_card(storage, data["question_id"])
        await message.answer("✅ Ответ сохранён.")
        for chunk in split_text(text, TELEGRAM_LIMIT - 100)[:-1]:
            await message.answer(chunk)
        await message.answer(split_text(text, TELEGRAM_LIMIT - 100)[-1], reply_markup=markup)

    @router.callback_query(F.data.startswith("a:delq:"))
    async def on_delete_question(callback: CallbackQuery, storage: Storage) -> None:
        q = storage.get_question(int(callback.data.split(":")[2]))
        if q is None:
            await _show(callback, "Вопрос не найден.", _kb([_BACK]))
            return
        await _show(
            callback,
            f"Удалить вопрос «{escape(short(q.text, 200))}»? История ответов на него тоже удалится.",
            _kb([("🗑 Да, удалить", f"a:delq!:{q.id}"), ("Отмена", f"a:q:{q.id}")]),
        )

    @router.callback_query(F.data.startswith("a:delq!:"))
    async def on_delete_question_confirmed(callback: CallbackQuery, storage: Storage) -> None:
        q = storage.get_question(int(callback.data.split(":")[2]))
        if q is not None:
            storage.delete_question(q.id)
        await _show(callback, "🗑 Вопрос удалён.")
        view = _category_page(storage, q.category_id, 0) if q else None
        if view:
            await callback.message.answer(*view[:1], reply_markup=view[1])

    @router.callback_query(F.data.startswith("a:delcat:"))
    async def on_delete_category(callback: CallbackQuery, storage: Storage) -> None:
        category = storage.get_category(int(callback.data.split(":")[2]))
        if category is None:
            await _show(callback, "Категория не найдена.", _kb([_BACK]))
            return
        await _show(
            callback,
            f"Удалить категорию «{escape(category.name)}» и все её вопросы ({category.questions})?",
            _kb([("🗑 Да, удалить", f"a:delcat!:{category.id}"), ("Отмена", f"a:cat:{category.id}:0")]),
        )

    @router.callback_query(F.data.startswith("a:delcat!:"))
    async def on_delete_category_confirmed(callback: CallbackQuery, storage: Storage) -> None:
        storage.delete_category(int(callback.data.split(":")[2]))
        await _show(callback, "🗑 Категория удалена.", _kb([("📚 Вопросы и ответы", "a:browse")], [_BACK]))

    @router.message(Command("skip"))
    async def on_stray_skip(message: Message) -> None:
        await message.answer("Сейчас нечего пропускать. Меню: /admin")

    return router
