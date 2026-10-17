"""A fake Telegram: updates go through the real aiogram Dispatcher, Bot API calls are recorded instead of sent."""

from datetime import datetime
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, GetFile, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Document, File, Message, Update, User

from bot.app import create_dispatcher
from bot.grader import Grader
from bot.storage import Storage

ADMIN_ID = 100
USER_ID = 200


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.files: dict[str, bytes] = {}
        self._ids = count(1000)

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id=method.file_id, file_path=method.file_id)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if getattr(method, "text", None) is not None and getattr(method, "chat_id", None) is not None:
            return Message(
                message_id=next(self._ids),
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield self.files[url.rsplit("/", 1)[-1]]

    async def close(self):
        pass


class FakeLLM:
    label = "fake:model"

    def __init__(self):
        self.calls = []
        self.result = {"strengths": ["Верно"], "missing": ["Деталь"], "mistakes": [], "summary": "Хороший ответ", "score": 8, "followUp": "А почему?"}

    async def chat_json(self, system, user, schema):
        self.calls.append(user)
        return self.result


class Harness:
    def __init__(self, storage: Storage, llm: FakeLLM):
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session)
        self.dp = create_dispatcher(storage, Grader(llm), frozenset({ADMIN_ID}))
        self._ids = count(1)
        self._seen = 0

    def _user(self, user_id):
        return User(id=user_id, is_bot=False, first_name=f"User{user_id}", username=f"user{user_id}")

    async def _feed(self, update: Update) -> list[TelegramMethod]:
        await self.dp.feed_update(self.bot, update)
        new = self.session.requests[self._seen :]
        self._seen = len(self.session.requests)
        return new

    async def send(self, user_id: int, text: str | None = None, document: tuple[str, bytes] | None = None):
        doc = None
        if document:
            name, content = document
            self.session.files[name] = content
            doc = Document(file_id=name, file_unique_id=name, file_name=name)
        msg = Message(
            message_id=next(self._ids),
            date=datetime.now(),
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id),
            text=text,
            document=doc,
        )
        return Replies(await self._feed(Update(update_id=next(self._ids), message=msg)))

    async def click(self, user_id: int, button: str):
        """Clicks a button (by its visible text, substring match) on the latest message that has it."""
        data = self.find_button(button)
        msg = Message(message_id=1, date=datetime.now(), chat=Chat(id=user_id, type="private"), text="...")
        cq = CallbackQuery(id=str(next(self._ids)), from_user=self._user(user_id), chat_instance="ci", message=msg, data=data)
        return Replies(await self._feed(Update(update_id=next(self._ids), callback_query=cq)))

    def find_button(self, label: str) -> str:
        for method in reversed(self.session.requests):
            markup = getattr(method, "reply_markup", None)
            for row in getattr(markup, "inline_keyboard", None) or []:
                for b in row:
                    if label in b.text:
                        return b.callback_data
        raise AssertionError(f"button {label!r} not found")


class Replies(list):
    @property
    def texts(self) -> list[str]:
        return [m.text for m in self if getattr(m, "text", None)]

    @property
    def text(self) -> str:
        return "\n".join(self.texts)

    @property
    def buttons(self) -> list[str]:
        return [b.text for m in self for row in (getattr(getattr(m, "reply_markup", None), "inline_keyboard", None) or []) for b in row]


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def tg(storage, llm):
    return Harness(storage, llm)
