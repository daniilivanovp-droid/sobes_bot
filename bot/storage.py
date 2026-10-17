"""SQLite storage: categories, questions with reference answers, users and their attempts."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    answer TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,  -- Telegram user id
    username TEXT,
    full_name TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('ai', 'reference')),
    score INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_user_question ON attempts(user_id, question_id);
"""


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    questions: int = 0
    answered: int = 0


@dataclass(frozen=True)
class Question:
    id: int
    category_id: int
    category_name: str
    text: str
    answer: str | None


@dataclass(frozen=True)
class CategoryStats:
    name: str
    attempts: int
    avg_score: float | None


@dataclass(frozen=True)
class UserRow:
    display_name: str
    attempts: int
    avg_score: float | None


@dataclass(frozen=True)
class Stats:
    users_total: int
    users_new_7d: int
    users_active_1d: int
    users_active_7d: int
    attempts_total: int
    ai_checks: int
    reference_views: int
    avg_score: float | None
    questions_total: int
    questions_answered: int
    by_category: list[CategoryStats]
    top_users: list[UserRow]


@dataclass(frozen=True)
class UserStats:
    attempts: int
    ai_checks: int
    questions_practiced: int
    avg_score: float | None


_QUESTION_SELECT = """
SELECT q.id, q.category_id, c.name, q.text, q.answer
FROM questions q JOIN categories c ON c.id = q.category_id
"""


class Storage:
    def __init__(self, path: str, clock: Callable[[], datetime] = datetime.now):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._clock = clock

    def close(self) -> None:
        self._db.close()

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _ago(self, **kwargs) -> str:
        return (self._clock() - timedelta(**kwargs)).isoformat(timespec="seconds")

    # --- categories ---------------------------------------------------------

    def add_category(self, name: str) -> Category | None:
        """Returns None if a category with this name (any case) already exists."""
        name = name.strip()
        try:
            with self._db:
                cur = self._db.execute("INSERT INTO categories(name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            return None
        return Category(cur.lastrowid, name)

    def get_or_create_category(self, name: str) -> Category:
        name = name.strip()
        row = self._db.execute("SELECT id, name FROM categories WHERE name = ?", (name,)).fetchone()
        return Category(*row) if row else self.add_category(name)

    def get_category(self, category_id: int) -> Category | None:
        return next((c for c in self.list_categories() if c.id == category_id), None)

    def list_categories(self) -> list[Category]:
        rows = self._db.execute(
            """SELECT c.id, c.name, COUNT(q.id), COUNT(q.answer)
               FROM categories c LEFT JOIN questions q ON q.category_id = c.id
               GROUP BY c.id ORDER BY c.name COLLATE NOCASE"""
        ).fetchall()
        return [Category(*r) for r in rows]

    def list_practice_categories(self) -> list[Category]:
        return [c for c in self.list_categories() if c.answered > 0]

    def delete_category(self, category_id: int) -> bool:
        with self._db:
            return self._db.execute("DELETE FROM categories WHERE id = ?", (category_id,)).rowcount > 0

    # --- questions ----------------------------------------------------------

    def add_question(self, category_id: int, text: str, answer: str | None = None) -> Question:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO questions(category_id, text, answer, created_at) VALUES (?, ?, ?, ?)",
                (category_id, text.strip(), (answer or "").strip() or None, self._now()),
            )
        return self.get_question(cur.lastrowid)

    def get_question(self, question_id: int) -> Question | None:
        row = self._db.execute(_QUESTION_SELECT + " WHERE q.id = ?", (question_id,)).fetchone()
        return Question(*row) if row else None

    def list_questions(self, category_id: int) -> list[Question]:
        rows = self._db.execute(_QUESTION_SELECT + " WHERE q.category_id = ? ORDER BY q.id", (category_id,)).fetchall()
        return [Question(*r) for r in rows]

    def set_answer(self, question_id: int, answer: str) -> bool:
        with self._db:
            cur = self._db.execute("UPDATE questions SET answer = ? WHERE id = ?", (answer.strip() or None, question_id))
        return cur.rowcount > 0

    def delete_question(self, question_id: int) -> bool:
        with self._db:
            return self._db.execute("DELETE FROM questions WHERE id = ?", (question_id,)).rowcount > 0

    # --- practice -----------------------------------------------------------

    def next_question(self, user_id: int, category_id: int, exclude_id: int | None = None) -> Question | None:
        """Questions with a reference answer: never practiced by this user first, then practiced longest ago."""
        rows = self._db.execute(
            _QUESTION_SELECT
            + """ LEFT JOIN (SELECT question_id, MAX(created_at) AS last FROM attempts WHERE user_id = ? GROUP BY question_id) a
                  ON a.question_id = q.id
                WHERE q.category_id = ? AND q.answer IS NOT NULL
                ORDER BY a.last IS NOT NULL, a.last, RANDOM()""",
            (user_id, category_id),
        ).fetchall()
        questions = [Question(*r) for r in rows]
        preferred = [q for q in questions if q.id != exclude_id]
        return (preferred or questions or [None])[0]

    def record_attempt(self, user_id: int, question_id: int, mode: str, score: int | None = None) -> None:
        now = self._now()
        with self._db:
            self._db.execute(
                "INSERT INTO attempts(user_id, question_id, mode, score, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, question_id, mode, score, now),
            )
            self._db.execute(
                """INSERT INTO users(id, first_seen, last_seen) VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen""",
                (user_id, now, now),
            )

    # --- users & stats ------------------------------------------------------

    def touch_user(self, user_id: int, username: str | None, full_name: str | None) -> None:
        now = self._now()
        with self._db:
            self._db.execute(
                """INSERT INTO users(id, username, full_name, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name,
                                                 last_seen = excluded.last_seen""",
                (user_id, username, full_name, now, now),
            )

    def _scalar(self, sql: str, *params):
        return self._db.execute(sql, params).fetchone()[0]

    def stats(self, top: int = 10) -> Stats:
        day, week = self._ago(days=1), self._ago(days=7)
        by_category = [
            CategoryStats(*r)
            for r in self._db.execute(
                """SELECT c.name, COUNT(a.id) AS n, AVG(a.score)
                   FROM attempts a JOIN questions q ON q.id = a.question_id JOIN categories c ON c.id = q.category_id
                   GROUP BY c.id ORDER BY n DESC, c.name"""
            ).fetchall()
        ]
        top_users = [
            UserRow(
                f"@{username}" if username else (full_name or f"id {uid}"),
                n,
                avg,
            )
            for uid, username, full_name, n, avg in self._db.execute(
                """SELECT a.user_id, u.username, u.full_name, COUNT(*) AS n, AVG(a.score)
                   FROM attempts a LEFT JOIN users u ON u.id = a.user_id
                   GROUP BY a.user_id ORDER BY n DESC LIMIT ?""",
                (top,),
            ).fetchall()
        ]
        return Stats(
            users_total=self._scalar("SELECT COUNT(*) FROM users"),
            users_new_7d=self._scalar("SELECT COUNT(*) FROM users WHERE first_seen >= ?", week),
            users_active_1d=self._scalar("SELECT COUNT(*) FROM users WHERE last_seen >= ?", day),
            users_active_7d=self._scalar("SELECT COUNT(*) FROM users WHERE last_seen >= ?", week),
            attempts_total=self._scalar("SELECT COUNT(*) FROM attempts"),
            ai_checks=self._scalar("SELECT COUNT(*) FROM attempts WHERE mode = 'ai'"),
            reference_views=self._scalar("SELECT COUNT(*) FROM attempts WHERE mode = 'reference'"),
            avg_score=self._scalar("SELECT AVG(score) FROM attempts WHERE mode = 'ai'"),
            questions_total=self._scalar("SELECT COUNT(*) FROM questions"),
            questions_answered=self._scalar("SELECT COUNT(*) FROM questions WHERE answer IS NOT NULL"),
            by_category=by_category,
            top_users=top_users,
        )

    def user_stats(self, user_id: int) -> UserStats:
        row = self._db.execute(
            """SELECT COUNT(*), COUNT(CASE WHEN mode = 'ai' THEN 1 END), COUNT(DISTINCT question_id), AVG(score)
               FROM attempts WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        return UserStats(*row)
