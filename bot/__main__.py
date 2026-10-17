"""Entry point: python -m bot"""

import asyncio
import logging
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from dotenv import load_dotenv

from bot.app import create_dispatcher
from bot.config import ConfigError, load_settings
from bot.grader import Grader
from bot.llm import make_llm_client
from bot.storage import Storage

log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="start", description="Выбрать категорию и тренироваться"),
    BotCommand(command="mystats", description="Моя статистика"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
]


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as e:
        sys.exit(f"Ошибка настройки: {e}")

    storage = Storage(settings.db_path)
    grader = Grader(make_llm_client(settings))
    log.info("База: %s, проверка ответов: %s", settings.db_path, grader.label)
    if not settings.admin_ids:
        log.warning("ADMIN_IDS пуст: панель администратора недоступна никому. Узнайте свой ID командой /id")

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher(storage, grader, settings.admin_ids)
    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        storage.close()


if __name__ == "__main__":
    asyncio.run(main())
