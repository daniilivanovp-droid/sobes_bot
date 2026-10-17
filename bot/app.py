from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.grader import Grader
from bot.handlers import admin, common, user
from bot.storage import Storage


def create_dispatcher(storage: Storage, grader: Grader, admin_ids: frozenset[int]) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Injected into handlers by parameter name.
    dp["storage"] = storage
    dp["grader"] = grader
    dp["admin_ids"] = admin_ids
    # Order matters: commands work in any state, admin handlers only match admins, user handlers catch the rest.
    dp.include_routers(common.create_router(), admin.create_router(admin_ids), user.create_router())
    return dp
