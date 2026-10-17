"""LLM clients for answer grading.

Groq (free, OpenAI-compatible API) is the default, as on the «Собес.Тренер» site.
Any other OpenAI-compatible API (OpenRouter, a local Ollama at /v1, ...) works via GRADER=openai.
"""

import json
from typing import Protocol

import httpx

from bot.config import Settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    label: str

    async def chat_json(self, system: str, user: str, schema: dict) -> dict: ...


class OpenAICompatibleClient:
    def __init__(self, name: str, base_url: str, api_key: str, model: str, http: httpx.AsyncClient | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.label = f"{'groq' if name == 'Groq' else 'openai'}:{model}"
        self._http = http or httpx.AsyncClient(timeout=60)

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        # Structured output occasionally fails validation on the provider side; one retry covers that.
        last_error = ""
        for _ in range(2):
            try:
                res = await self._http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as e:
                raise LLMError(f"{self.name} недоступен, проверьте интернет-соединение") from e
            if res.status_code in (401, 403):
                raise LLMError(f"{self.name}: ключ API не подошёл (ошибка {res.status_code})")
            if res.status_code == 429:
                raise LLMError(f"{self.name}: превышен лимит бесплатных запросов, попробуйте через минуту")
            if res.is_success:
                content = res.json().get("choices", [{}])[0].get("message", {}).get("content") or ""
                try:
                    return json.loads(content[content.index("{") : content.rindex("}") + 1])
                except ValueError:
                    last_error = f"{self.name} вернул ответ не в формате JSON"
                    continue
            last_error = f"{self.name} вернул ошибку {res.status_code}: {res.text[:200]}"
        raise LLMError(last_error)


def make_llm_client(settings: Settings) -> LLMClient | None:
    """None means grading without AI (keyword heuristic)."""
    grader = settings.grader or ("groq" if settings.groq_api_key else "heuristic")
    if grader == "groq" and settings.groq_api_key:
        return OpenAICompatibleClient("Groq", GROQ_BASE_URL, settings.groq_api_key, settings.groq_model)
    if grader == "openai" and settings.llm_base_url and settings.llm_model:
        return OpenAICompatibleClient("LLM API", settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return None
