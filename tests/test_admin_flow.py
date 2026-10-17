from tests.conftest import ADMIN_ID, USER_ID


async def test_admin_menu(tg):
    r = await tg.send(ADMIN_ID, "/admin")
    for label in ("Добавить категорию", "Добавить вопрос", "Импорт", "Вопросы и ответы", "Статистика"):
        assert any(label in b for b in r.buttons), label


async def test_add_category(tg, storage):
    await tg.send(ADMIN_ID, "/admin")
    r = await tg.click(ADMIN_ID, "Добавить категорию")
    assert "название" in r.text.lower()
    r = await tg.send(ADMIN_ID, "Spark")
    assert "Spark" in r.text
    assert [c.name for c in storage.list_categories()] == ["Spark"]


async def test_add_duplicate_category(tg, storage):
    storage.add_category("Spark")
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Добавить категорию")
    r = await tg.send(ADMIN_ID, "spark")
    assert "уже есть" in r.text
    assert len(storage.list_categories()) == 1


async def test_add_question_with_answer(tg, storage):
    spark = storage.add_category("Spark")
    await tg.send(ADMIN_ID, "/admin")
    r = await tg.click(ADMIN_ID, "Добавить вопрос")
    assert any("Spark" in b for b in r.buttons)
    await tg.click(ADMIN_ID, "Spark")
    r = await tg.send(ADMIN_ID, "Что такое RDD?")
    assert "эталонный ответ" in r.text.lower()
    r = await tg.send(ADMIN_ID, "Коллекция")
    assert "добавлен" in r.text
    [q] = storage.list_questions(spark.id)
    assert (q.text, q.answer) == ("Что такое RDD?", "Коллекция")


async def test_add_question_skip_answer(tg, storage):
    spark = storage.add_category("Spark")
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Добавить вопрос")
    await tg.click(ADMIN_ID, "Spark")
    await tg.send(ADMIN_ID, "Что такое DAG?")
    await tg.send(ADMIN_ID, "/skip")
    [q] = storage.list_questions(spark.id)
    assert q.answer is None


async def test_add_question_without_categories_suggests_creating_one(tg):
    await tg.send(ADMIN_ID, "/admin")
    r = await tg.click(ADMIN_ID, "Добавить вопрос")
    assert "Сначала добавьте категорию" in r.text


async def test_import_text(tg, storage):
    await tg.send(ADMIN_ID, "/admin")
    r = await tg.click(ADMIN_ID, "Импорт")
    assert "---" in r.text
    r = await tg.send(ADMIN_ID, "# Spark\nЧто такое RDD?\nКоллекция\n---\nЧто такое DAG?\n---\n# Airflow\nЧто такое DAG в Airflow?\nГраф задач")
    assert "3" in r.text
    cats = {c.name: c for c in storage.list_categories()}
    assert (cats["Spark"].questions, cats["Spark"].answered) == (2, 1)
    assert cats["Airflow"].answered == 1


async def test_import_without_section_goes_to_default_category(tg, storage):
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Импорт")
    await tg.send(ADMIN_ID, "Вопрос\nОтвет")
    assert [c.name for c in storage.list_categories()] == ["Общее"]


async def test_import_file(tg, storage):
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Импорт")
    r = await tg.send(ADMIN_ID, document=("bank.md", "# SQL\nЧто такое JOIN?\nСоединение таблиц".encode()))
    assert "1" in r.text
    assert storage.list_categories()[0].name == "SQL"


async def test_import_nothing_parsed(tg, storage):
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Импорт")
    r = await tg.send(ADMIN_ID, "---")
    assert "не нашёл" in r.text.lower()


async def test_browse_and_set_answer(tg, storage):
    spark = storage.add_category("Spark")
    q = storage.add_question(spark.id, "Что такое RDD?")
    await tg.send(ADMIN_ID, "/admin")
    r = await tg.click(ADMIN_ID, "Вопросы и ответы")
    assert any("Spark" in b for b in r.buttons)
    r = await tg.click(ADMIN_ID, "Spark")
    assert any("RDD" in b for b in r.buttons)
    r = await tg.click(ADMIN_ID, "RDD")
    assert "Эталонный ответ не задан" in r.text
    await tg.click(ADMIN_ID, "ответ")
    r = await tg.send(ADMIN_ID, "Коллекция")
    assert "сохранён" in r.text
    assert storage.get_question(q.id).answer == "Коллекция"


async def test_browse_paginates(tg, storage):
    spark = storage.add_category("Spark")
    for i in range(25):
        storage.add_question(spark.id, f"Вопрос номер {i}")
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Вопросы и ответы")
    r = await tg.click(ADMIN_ID, "Spark")
    assert any("Вопрос номер 0" in b for b in r.buttons)
    assert not any("Вопрос номер 24" in b for b in r.buttons)
    r = await tg.click(ADMIN_ID, "▶")
    assert any("Вопрос номер 10" in b for b in r.buttons)


async def test_delete_question_with_confirmation(tg, storage):
    spark = storage.add_category("Spark")
    q = storage.add_question(spark.id, "Что такое RDD?", "Коллекция")
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Вопросы и ответы")
    await tg.click(ADMIN_ID, "Spark")
    await tg.click(ADMIN_ID, "RDD")
    r = await tg.click(ADMIN_ID, "Удалить вопрос")
    assert "Удалить" in r.text
    assert storage.get_question(q.id) is not None
    r = await tg.click(ADMIN_ID, "Да, удалить")
    assert "удалён" in r.text
    assert storage.get_question(q.id) is None


async def test_delete_category_with_confirmation(tg, storage):
    spark = storage.add_category("Spark")
    storage.add_question(spark.id, "Q", "A")
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Вопросы и ответы")
    await tg.click(ADMIN_ID, "Spark")
    r = await tg.click(ADMIN_ID, "Удалить категорию")
    assert "1" in r.text  # warns how many questions will be removed
    await tg.click(ADMIN_ID, "Да, удалить")
    assert storage.list_categories() == []


async def test_stats(tg, storage):
    spark = storage.add_category("Spark")
    q = storage.add_question(spark.id, "Q", "A")
    storage.touch_user(USER_ID, "alice", "Alice")
    storage.record_attempt(USER_ID, q.id, "ai", score=6)
    storage.record_attempt(USER_ID, q.id, "reference")
    await tg.send(ADMIN_ID, "/admin")
    r = await tg.click(ADMIN_ID, "Статистика")
    for needle in ("Пользователей", "Проверок ИИ: 1", "Просмотров эталона: 1", "6.0", "Spark", "@alice"):
        assert needle in r.text, needle


async def test_cancel_leaves_input_state(tg, storage):
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Добавить категорию")
    r = await tg.send(ADMIN_ID, "/cancel")
    assert "Отменено" in r.text
    await tg.send(ADMIN_ID, "Spark")
    assert storage.list_categories() == []
