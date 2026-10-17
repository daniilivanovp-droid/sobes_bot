import json

import httpx
import pytest

from bot.grader import Grade, Grader, format_grade, heuristic_grade, verdict_for
from bot.llm import LLMError, OpenAICompatibleClient, make_llm_client
from bot.config import Settings


QUESTION = "Что такое RDD в Spark?"
REFERENCE = "RDD это неизменяемая распределённая коллекция объектов. Она восстанавливается по lineage."


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []
        self.label = "fake:model"

    async def chat_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        if self.error:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    "score,verdict",
    [(10, "Отлично"), (9, "Отлично"), (7, "Хорошо"), (5, "Удовлетворительно"), (3, "Слабо"), (0, "Не засчитано")],
)
def test_verdict_for(score, verdict):
    assert verdict_for(score) == verdict


async def test_grader_uses_llm_and_passes_question_reference_answer():
    client = FakeClient(
        {"strengths": ["Верно про неизменяемость"], "missing": ["lineage"], "mistakes": [], "summary": "Неплохо", "score": 7, "followUp": "А что такое lineage?"}
    )
    grade = await Grader(client).grade(QUESTION, REFERENCE, "Неизменяемая коллекция")
    assert grade.score == 7 and grade.verdict == "Хорошо" and grade.grader == "llm"
    assert grade.missing == ["lineage"] and grade.follow_up == "А что такое lineage?"
    _, user_prompt, schema = client.calls[0]
    assert QUESTION in user_prompt and REFERENCE in user_prompt and "Неизменяемая коллекция" in user_prompt
    assert "score" in schema["required"]


async def test_grader_clamps_score_and_fills_missing_fields():
    grade = await Grader(FakeClient({"score": 42})).grade(QUESTION, REFERENCE, "ответ")
    assert grade.score == 10 and grade.strengths == [] and grade.summary == ""


async def test_grader_without_client_uses_heuristic():
    grade = await Grader(None).grade(QUESTION, REFERENCE, "RDD это неизменяемая распределённая коллекция")
    assert grade.grader == "heuristic" and grade.score > 0


async def test_grader_falls_back_to_heuristic_when_llm_fails():
    grade = await Grader(FakeClient(error=LLMError("Groq: превышен лимит"))).grade(QUESTION, REFERENCE, "не знаю")
    assert grade.grader == "heuristic"
    assert "Groq: превышен лимит" in grade.summary


def test_heuristic_full_and_empty_answers():
    assert heuristic_grade(REFERENCE, REFERENCE).score == 10
    empty = heuristic_grade(REFERENCE, "не знаю")
    assert empty.score == 0 and empty.missing


def test_format_grade_contains_score_and_sections_and_escapes_html():
    text = format_grade(
        Grade(score=7, verdict="Хорошо", summary="Суть <верна>", strengths=["a"], missing=["b"], mistakes=["c"], follow_up="d?", grader="llm")
    )
    assert "7/10" in text and "Хорошо" in text and "&lt;верна&gt;" in text
    for part in ("a", "b", "c", "d?"):
        assert part in text


# --- OpenAI-compatible client (Groq) ----------------------------------------


def make_client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleClient("Groq", "https://api.groq.com/openai/v1", "gsk_test", "openai/gpt-oss-120b", http=http)


async def test_openai_client_sends_json_schema_request_and_parses_answer():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": 'text {"score": 5} tail'}}]})

    result = await make_client(handler).chat_json("sys", "usr", {"type": "object"})
    assert result == {"score": 5}
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer gsk_test"
    assert seen["body"]["model"] == "openai/gpt-oss-120b"
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}


@pytest.mark.parametrize("status,needle", [(401, "ключ"), (429, "лимит")])
async def test_openai_client_maps_errors(status, needle):
    with pytest.raises(LLMError, match=needle):
        await make_client(lambda r: httpx.Response(status)).chat_json("s", "u", {})


async def test_openai_client_retries_once_on_server_error():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, text="oops")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"score": 1}'}}]})

    assert await make_client(handler).chat_json("s", "u", {}) == {"score": 1}
    assert len(calls) == 2


async def test_openai_client_network_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(LLMError, match="недоступен"):
        await make_client(handler).chat_json("s", "u", {})


# --- choosing a backend -----------------------------------------------------


def settings(**kw):
    base = dict(bot_token="t", admin_ids=frozenset(), db_path=":memory:")
    base.update(kw)
    return Settings(**base)


def test_make_llm_client_prefers_groq_when_key_set():
    client = make_llm_client(settings(groq_api_key="gsk"))
    assert client.label == "groq:openai/gpt-oss-120b"


def test_make_llm_client_openai_compatible():
    client = make_llm_client(settings(grader="openai", llm_base_url="http://localhost:11434/v1/", llm_model="qwen3:8b"))
    assert client.label == "openai:qwen3:8b"
    assert client.base_url == "http://localhost:11434/v1"


def test_make_llm_client_heuristic():
    assert make_llm_client(settings()) is None
    assert make_llm_client(settings(grader="heuristic", groq_api_key="gsk")) is None
