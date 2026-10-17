from tests.conftest import ADMIN_ID, USER_ID


def seed(storage):
    spark = storage.add_category("Spark")
    storage.add_category("Пустая")
    q1 = storage.add_question(spark.id, "Что такое RDD?", "Неизменяемая распределённая коллекция")
    q2 = storage.add_question(spark.id, "Что такое DAG?", "Граф стадий")
    return spark, q1, q2


async def test_start_registers_user_and_shows_categories_with_answered_questions(tg, storage):
    seed(storage)
    r = await tg.send(USER_ID, "/start")
    assert "категорию" in r.text
    assert any("Spark" in b for b in r.buttons)
    assert not any("Пустая" in b for b in r.buttons)
    assert storage.stats().users_total == 1


async def test_start_without_questions(tg):
    r = await tg.send(USER_ID, "/start")
    assert "пока нет" in r.text


async def test_choose_category_shows_question_with_buttons(tg, storage):
    seed(storage)
    await tg.send(USER_ID, "/start")
    r = await tg.click(USER_ID, "Spark")
    assert "Что такое" in r.text
    assert "Показать эталон" in " ".join(r.buttons)


async def test_show_reference_without_answering_records_attempt(tg, storage):
    seed(storage)
    await tg.send(USER_ID, "/start")
    r = await tg.click(USER_ID, "Spark")
    r = await tg.click(USER_ID, "Показать эталон")
    assert "Неизменяемая распределённая коллекция" in r.text or "Граф стадий" in r.text
    assert storage.user_stats(USER_ID).attempts == 1
    assert "Следующий вопрос" in " ".join(r.buttons)


async def test_answer_then_check_with_ai(tg, storage, llm):
    seed(storage)
    await tg.send(USER_ID, "/start")
    await tg.click(USER_ID, "Spark")
    r = await tg.send(USER_ID, "Мой ответ про коллекцию")
    assert "Проверить ИИ" in " ".join(r.buttons) and "Показать эталон" in " ".join(r.buttons)

    r = await tg.click(USER_ID, "Проверить ИИ")
    assert "8/10" in r.text and "Хорошо" in r.text and "А почему?" in r.text
    assert "Эталон" in r.text
    assert "Мой ответ про коллекцию" in llm.calls[0]
    stats = storage.user_stats(USER_ID)
    assert (stats.ai_checks, stats.avg_score) == (1, 8)


async def test_new_answer_replaces_previous_one(tg, storage, llm):
    seed(storage)
    await tg.send(USER_ID, "/start")
    await tg.click(USER_ID, "Spark")
    await tg.send(USER_ID, "черновик")
    await tg.send(USER_ID, "финальный ответ")
    await tg.click(USER_ID, "Проверить ИИ")
    assert "финальный ответ" in llm.calls[0] and "черновик" not in llm.calls[0]


async def test_check_without_answer_asks_to_write_one(tg, storage, llm):
    seed(storage)
    await tg.send(USER_ID, "/start")
    await tg.click(USER_ID, "Spark")
    await tg.send(USER_ID, "ответ")
    await tg.click(USER_ID, "Следующий вопрос")
    # The old "Проверить ИИ" button is from the previous question; the answer was reset.
    r = await tg.click(USER_ID, "Проверить ИИ")
    assert "Сначала напишите ответ" in r.text
    assert llm.calls == []


async def test_next_question_gives_another_question(tg, storage):
    _, q1, q2 = seed(storage)
    await tg.send(USER_ID, "/start")
    first = (await tg.click(USER_ID, "Spark")).text
    second = (await tg.click(USER_ID, "Следующий вопрос")).text
    assert q1.text in first + second and q2.text in first + second


async def test_text_without_active_question_hints_to_start(tg, storage):
    seed(storage)
    r = await tg.send(USER_ID, "привет")
    assert "/start" in r.text


async def test_deleted_question_is_handled(tg, storage):
    _, q1, q2 = seed(storage)
    await tg.send(USER_ID, "/start")
    await tg.click(USER_ID, "Spark")
    storage.delete_question(q1.id)
    storage.delete_question(q2.id)
    r = await tg.send(USER_ID, "ответ")
    assert "удалён" in r.text


async def test_long_reference_is_split_into_several_messages(tg, storage):
    spark = storage.add_category("Spark")
    storage.add_question(spark.id, "Длинный вопрос", "слово " * 2000)
    await tg.send(USER_ID, "/start")
    await tg.click(USER_ID, "Spark")
    r = await tg.click(USER_ID, "Показать эталон")
    assert len(r.texts) >= 3
    assert all(len(t) <= 4096 for t in r.texts)


async def test_mystats_and_id(tg, storage):
    seed(storage)
    await tg.send(USER_ID, "/start")
    await tg.click(USER_ID, "Spark")
    await tg.click(USER_ID, "Показать эталон")
    r = await tg.send(USER_ID, "/mystats")
    assert "1" in r.text
    r = await tg.send(USER_ID, "/id")
    assert str(USER_ID) in r.text


async def test_user_cannot_open_admin_panel(tg, storage):
    seed(storage)
    r = await tg.send(USER_ID, "/admin")
    assert "нет доступа" in r.text.lower()
    assert not r.buttons


async def test_user_cannot_press_admin_buttons(tg, storage):
    spark, q1, _ = seed(storage)
    await tg.send(ADMIN_ID, "/admin")
    await tg.click(ADMIN_ID, "Вопросы и ответы")
    await tg.click(ADMIN_ID, "Spark")
    await tg.click(ADMIN_ID, "RDD")
    await tg.click(ADMIN_ID, "Удалить вопрос")
    # A regular user replays the admin's confirm button.
    await tg.click(USER_ID, "Да, удалить")
    assert storage.get_question(q1.id) is not None
