"""Commands available in any state."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers import admin, user
from bot.storage import Storage


async def start(message: Message, state: FSMContext, storage: Storage, admin_ids: frozenset[int]) -> None:
    await state.clear()
    storage.touch_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    hint = "\n\nВы администратор: панель управления по команде /admin." if message.from_user.id in admin_ids else ""
    await message.answer(
        "Привет! Здесь можно потренироваться отвечать на вопросы с реальных собеседований.\n\n"
        "Выберите категорию, напишите ответ на вопрос, а затем проверьте его ИИ или сразу посмотрите эталон.\n"
        "Команды: /start — выбрать категорию, /mystats — моя статистика." + hint
    )
    await user.send_categories(message, storage)


async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


async def my_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


async def my_stats(message: Message, storage: Storage) -> None:
    s = storage.user_stats(message.from_user.id)
    avg = f"{s.avg_score:.1f}" if s.avg_score is not None else "—"
    await message.answer(
        "<b>Моя статистика</b>\n"
        f"Ответов и просмотров эталона: {s.attempts}\n"
        f"Разных вопросов: {s.questions_practiced}\n"
        f"Проверок ИИ: {s.ai_checks}\n"
        f"Средняя оценка ИИ: {avg}"
    )


async def admin_entry(message: Message, state: FSMContext, admin_ids: frozenset[int]) -> None:
    if message.from_user.id not in admin_ids:
        await message.answer("Нет доступа к панели администратора.")
        return
    await state.clear()
    await message.answer(admin.MENU_TEXT, reply_markup=admin.menu_kb())


def create_router() -> Router:
    router = Router(name="common")
    router.message.register(start, CommandStart())
    router.message.register(cancel, Command("cancel"))
    router.message.register(my_id, Command("id"))
    router.message.register(my_stats, Command("mystats"))
    router.message.register(admin_entry, Command("admin"))
    return router
