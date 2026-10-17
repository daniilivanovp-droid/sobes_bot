from datetime import datetime, timedelta

import pytest

from bot.storage import Storage


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, 12, 0, 0)

    def __call__(self):
        return self.now

    def tick(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def storage(clock):
    s = Storage(":memory:", clock=clock)
    yield s
    s.close()


# --- categories -------------------------------------------------------------


def test_add_and_list_categories_sorted_by_name(storage):
    storage.add_category("Spark")
    storage.add_category("Airflow")
    assert [c.name for c in storage.list_categories()] == ["Airflow", "Spark"]


def test_get_or_create_category_is_case_insensitive(storage):
    spark = storage.get_or_create_category("Spark")
    assert storage.get_or_create_category("  spark ").id == spark.id
    assert len(storage.list_categories()) == 1


def test_add_category_returns_none_for_duplicate(storage):
    storage.add_category("Spark")
    assert storage.add_category("SPARK") is None


def test_categories_show_question_counts(storage):
    spark = storage.add_category("Spark")
    storage.add_question(spark.id, "Q1", "A1")
    storage.add_question(spark.id, "Q2")
    [c] = storage.list_categories()
    assert (c.questions, c.answered) == (2, 1)


def test_practice_categories_only_include_answered_questions(storage):
    spark = storage.add_category("Spark")
    airflow = storage.add_category("Airflow")
    storage.add_question(spark.id, "Q1", "A1")
    storage.add_question(airflow.id, "Q2")
    assert [c.name for c in storage.list_practice_categories()] == ["Spark"]


def test_delete_category_removes_its_questions(storage):
    spark = storage.add_category("Spark")
    q = storage.add_question(spark.id, "Q1", "A1")
    assert storage.delete_category(spark.id) is True
    assert storage.get_category(spark.id) is None
    assert storage.get_question(q.id) is None
    assert storage.delete_category(spark.id) is False


# --- questions --------------------------------------------------------------


def test_add_question_and_set_answer(storage):
    spark = storage.add_category("Spark")
    q = storage.add_question(spark.id, "Что такое RDD?")
    assert q.answer is None and q.category_name == "Spark"
    assert storage.set_answer(q.id, "Коллекция") is True
    assert storage.get_question(q.id).answer == "Коллекция"
    assert storage.set_answer(9999, "x") is False


def test_list_questions_in_category_in_insertion_order(storage):
    spark = storage.add_category("Spark")
    other = storage.add_category("Other")
    storage.add_question(spark.id, "Q1")
    storage.add_question(other.id, "X")
    storage.add_question(spark.id, "Q2")
    assert [q.text for q in storage.list_questions(spark.id)] == ["Q1", "Q2"]


def test_delete_question(storage):
    spark = storage.add_category("Spark")
    q = storage.add_question(spark.id, "Q1")
    assert storage.delete_question(q.id) is True
    assert storage.get_question(q.id) is None
    assert storage.delete_question(q.id) is False


# --- practice ---------------------------------------------------------------


def test_next_question_prefers_never_practiced_then_oldest(storage, clock):
    spark = storage.add_category("Spark")
    q1 = storage.add_question(spark.id, "Q1", "A1")
    q2 = storage.add_question(spark.id, "Q2", "A2")
    storage.add_question(spark.id, "Без ответа")
    user = 1
    storage.record_attempt(user, q1.id, "reference")
    assert storage.next_question(user, spark.id).id == q2.id
    clock.tick(minutes=1)
    storage.record_attempt(user, q2.id, "ai", score=7)
    # Both practiced now: the one practiced longer ago comes first.
    assert storage.next_question(user, spark.id).id == q1.id


def test_next_question_excludes_current_when_possible(storage):
    spark = storage.add_category("Spark")
    q1 = storage.add_question(spark.id, "Q1", "A1")
    q2 = storage.add_question(spark.id, "Q2", "A2")
    assert storage.next_question(1, spark.id, exclude_id=q1.id).id == q2.id
    # The only question in a category is still returned.
    solo = storage.add_category("Solo")
    only = storage.add_question(solo.id, "Only", "A")
    assert storage.next_question(1, solo.id, exclude_id=only.id).id == only.id


def test_next_question_none_when_category_has_no_answered_questions(storage):
    spark = storage.add_category("Spark")
    storage.add_question(spark.id, "Q1")
    assert storage.next_question(1, spark.id) is None


# --- users & stats ----------------------------------------------------------


def test_touch_user_creates_and_updates(storage, clock):
    storage.touch_user(1, "alice", "Alice A")
    clock.tick(days=1)
    storage.touch_user(1, "alice2", "Alice B")
    stats = storage.stats()
    assert stats.users_total == 1


def test_stats(storage, clock):
    spark = storage.add_category("Spark")
    airflow = storage.add_category("Airflow")
    q1 = storage.add_question(spark.id, "Q1", "A1")
    q2 = storage.add_question(airflow.id, "Q2", "A2")

    storage.touch_user(1, "old", "Old User")
    storage.record_attempt(1, q1.id, "reference")
    clock.tick(days=10)
    storage.touch_user(2, "alice", "Alice")
    storage.touch_user(3, None, "Bob")
    storage.record_attempt(2, q1.id, "ai", score=8)
    storage.record_attempt(2, q2.id, "ai", score=4)
    storage.record_attempt(3, q1.id, "reference")

    s = storage.stats()
    assert s.users_total == 3
    assert s.users_new_7d == 2
    assert s.users_active_7d == 2
    assert s.users_active_1d == 2
    assert s.attempts_total == 4
    assert s.ai_checks == 2
    assert s.reference_views == 2
    assert s.avg_score == pytest.approx(6.0)
    assert [(c.name, c.attempts) for c in s.by_category] == [("Spark", 3), ("Airflow", 1)]
    assert s.by_category[0].avg_score == pytest.approx(8.0)
    assert [(u.display_name, u.attempts) for u in s.top_users][:1] == [("@alice", 2)]


def test_user_stats(storage):
    spark = storage.add_category("Spark")
    q1 = storage.add_question(spark.id, "Q1", "A1")
    q2 = storage.add_question(spark.id, "Q2", "A2")
    storage.record_attempt(5, q1.id, "ai", score=6)
    storage.record_attempt(5, q1.id, "ai", score=10)
    storage.record_attempt(5, q2.id, "reference")
    s = storage.user_stats(5)
    assert (s.attempts, s.ai_checks, s.questions_practiced) == (3, 2, 2)
    assert s.avg_score == pytest.approx(8.0)


def test_data_persists_in_file(tmp_path, clock):
    path = tmp_path / "bot.db"
    s = Storage(str(path), clock=clock)
    s.add_category("Spark")
    s.close()
    s2 = Storage(str(path), clock=clock)
    assert [c.name for c in s2.list_categories()] == ["Spark"]
    s2.close()
