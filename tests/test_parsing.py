from bot.parsing import ParsedQuestion, parse_question_blocks


def test_blocks_are_split_by_dashes_first_line_is_question():
    raw = "Что такое RDD?\nНеизменяемая распределённая коллекция.\n---\nЧто такое DAG?\nГраф задач."
    assert parse_question_blocks(raw) == [
        ParsedQuestion(category=None, text="Что такое RDD?", answer="Неизменяемая распределённая коллекция."),
        ParsedQuestion(category=None, text="Что такое DAG?", answer="Граф задач."),
    ]


def test_section_header_applies_to_following_blocks():
    raw = "# Spark\nВопрос 1\nОтвет 1\n---\nВопрос 2\nОтвет 2\n---\n## Airflow\nВопрос 3\nОтвет 3"
    assert [(q.category, q.text) for q in parse_question_blocks(raw)] == [
        ("Spark", "Вопрос 1"),
        ("Spark", "Вопрос 2"),
        ("Airflow", "Вопрос 3"),
    ]


def test_prefixes_are_stripped_and_multiline_answer_kept():
    raw = "В: Что такое executor?\nО: Процесс на воркере.\nВыполняет задачи."
    [q] = parse_question_blocks(raw)
    assert q.text == "Что такое executor?"
    assert q.answer == "Процесс на воркере.\nВыполняет задачи."


def test_question_without_answer_is_kept_with_empty_answer():
    [q] = parse_question_blocks("# Spark\nЧто такое shuffle?")
    assert q == ParsedQuestion(category="Spark", text="Что такое shuffle?", answer=None)


def test_empty_blocks_and_crlf_are_ignored():
    assert parse_question_blocks("\r\n---\r\n  \r\n---\r\n") == []
