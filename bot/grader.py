"""Grading an answer against the reference. Prompt and scale match the «Собес.Тренер» site."""

import logging
import re
from dataclasses import dataclass, field
from html import escape

from bot.llm import LLMClient, LLMError

log = logging.getLogger(__name__)

VERDICTS = ("Отлично", "Хорошо", "Удовлетворительно", "Слабо", "Не засчитано")

# Lists come before the score so that smaller models reason about coverage first, then score.
GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "strengths": {"type": "array", "items": {"type": "string"}, "description": "Что в ответе верно"},
        "missing": {"type": "array", "items": {"type": "string"}, "description": "Что из эталона не прозвучало"},
        "mistakes": {"type": "array", "items": {"type": "string"}, "description": "Фактические ошибки и неточности"},
        "summary": {"type": "string", "description": "2-3 предложения: общее впечатление интервьюера"},
        "score": {"type": "integer", "description": "Оценка от 0 до 10"},
        "followUp": {"type": "string", "description": "Уточняющий вопрос, который задал бы интервьюер"},
    },
    "required": ["strengths", "missing", "mistakes", "summary", "score", "followUp"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Ты опытный технический интервьюер на реальном собеседовании. Кандидат отвечает на вопрос письменно, у тебя есть эталонный ответ.

Оцени ответ кандидата так, как оценил бы его на собеседовании:
- Сравнивай по смыслу, а не по формулировкам. Другие слова или порядок изложения не снижают оценку.
- Главное: покрыты ли ключевые идеи эталона и нет ли фактических ошибок. Верные дополнения сверх эталона засчитываются в плюс.
- Фактическая ошибка в ключевом утверждении снижает оценку сильнее, чем упущенная деталь. Ответ не по теме или «не знаю» получает 0-1.
- Не штрафуй за опечатки.
- Шкала: 9-10 отлично (все ключевые идеи, без ошибок), 7-8 хорошо (суть верна, упущены детали), 5-6 удовлетворительно (половина ключевых идей), 3-4 слабо (отдельные верные мысли), 0-2 не засчитано.
- Пиши по-русски, коротко и по делу, обращаясь к кандидату на «вы». Пункты в списках короткие. Если пунктов нет, оставь список пустым.
- Верни только JSON по заданной схеме."""


@dataclass
class Grade:
    score: int
    verdict: str
    summary: str
    strengths: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)
    follow_up: str = ""
    grader: str = "llm"  # llm | heuristic


def verdict_for(score: int) -> str:
    if score >= 9:
        return VERDICTS[0]
    if score >= 7:
        return VERDICTS[1]
    if score >= 5:
        return VERDICTS[2]
    if score >= 3:
        return VERDICTS[3]
    return VERDICTS[4]


def _clamp(n: float) -> int:
    return max(0, min(10, round(n)))


def _strings(value) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def user_prompt(question: str, reference: str, answer: str) -> str:
    return (
        f"<question>\n{question}\n</question>\n\n"
        f"<reference_answer>\n{reference}\n</reference_answer>\n\n"
        f"<candidate_answer>\n{answer}\n</candidate_answer>"
    )


class Grader:
    def __init__(self, client: LLMClient | None):
        self.client = client

    @property
    def label(self) -> str:
        return self.client.label if self.client else "heuristic (без ИИ)"

    async def grade(self, question: str, reference: str, answer: str) -> Grade:
        if self.client is None:
            return heuristic_grade(reference, answer)
        try:
            parsed = await self.client.chat_json(SYSTEM_PROMPT, user_prompt(question, reference, answer), GRADE_SCHEMA)
        except LLMError as e:
            log.warning("LLM grading failed: %s", e)
            grade = heuristic_grade(reference, answer)
            grade.summary = f"ИИ сейчас недоступен ({e}). {grade.summary}"
            return grade
        try:
            score = _clamp(float(parsed.get("score", 0)))
        except (TypeError, ValueError):
            score = 0
        return Grade(
            score=score,
            verdict=verdict_for(score),
            summary=str(parsed.get("summary") or ""),
            strengths=_strings(parsed.get("strengths")),
            missing=_strings(parsed.get("missing")),
            mistakes=_strings(parsed.get("mistakes")),
            follow_up=str(parsed.get("followUp") or ""),
            grader="llm",
        )


# Fallback without AI: compares key terms of the reference with the answer.
_STOP_WORDS = set(
    "это этот эта эти который которая которые также чтобы когда если потому может можно нужно очень более менее "
    "тоже только через после перед между будет были было есть быть просто такой такие такая всего всех всегда "
    "where which that this with from have will when there their about would could should into than then them they what".split()
)


def _stems(text: str) -> list[str]:
    words = re.findall(r"[a-zа-яё0-9]+", text.lower())
    return [w[:6] for w in words if len(w) >= 4 and w not in _STOP_WORDS]


def heuristic_grade(reference: str, answer: str) -> Grade:
    answer_stems = set(_stems(answer))
    ref_stems = list(dict.fromkeys(_stems(reference)))
    covered = [s for s in ref_stems if s in answer_stems]
    recall = len(covered) / len(ref_stems) if ref_stems else 0
    score = _clamp(recall * 12)  # full coverage is rarely verbatim, so allow some slack

    strengths, missing = [], []
    for sentence in (s.strip() for s in re.split(r"(?<=[.!?\n])\s+", reference)):
        st = set(_stems(sentence))
        if not st:
            continue
        hit = len(st & answer_stems) / len(st)
        (strengths if hit >= 0.5 else missing).append(sentence)

    return Grade(
        score=score,
        verdict=verdict_for(score),
        summary=f"Упрощённая оценка без ИИ: в ответе прозвучало {len(covered)} из {len(ref_stems)} ключевых понятий эталона.",
        strengths=strengths[:5],
        missing=missing[:5],
        grader="heuristic",
    )


def format_grade(grade: Grade) -> str:
    """HTML for Telegram (parse_mode=HTML)."""
    parts = [f"<b>Оценка: {grade.score}/10 — {escape(grade.verdict)}</b>"]
    if grade.summary:
        parts.append(escape(grade.summary))
    for title, items in (("✅ Что хорошо", grade.strengths), ("➖ Чего не хватило", grade.missing), ("❌ Ошибки", grade.mistakes)):
        if items:
            parts.append(f"<b>{title}</b>\n" + "\n".join(f"• {escape(i)}" for i in items))
    if grade.follow_up:
        parts.append(f"<b>❓ Уточняющий вопрос</b>\n{escape(grade.follow_up)}")
    return "\n\n".join(parts)
