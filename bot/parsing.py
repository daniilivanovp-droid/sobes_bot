"""Bulk import format, same as on the «Собес.Тренер» site.

Questions are separated by a line of "---". In each block the first line is the
question and the rest is the reference answer (it may be empty and added later).
A line "# Раздел" at the start of a block sets the category for that block and
all following ones.
"""

import re
from dataclasses import dataclass

_SEPARATOR = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
_HEADER = re.compile(r"^#+\s")
_QUESTION_PREFIX = re.compile(r"^(в|вопрос|q)\s*[:.]\s*", re.IGNORECASE)
_ANSWER_PREFIX = re.compile(r"^\s*(о|ответ|a)\s*[:.]\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedQuestion:
    category: str | None
    text: str
    answer: str | None


def parse_question_blocks(raw: str) -> list[ParsedQuestion]:
    category: str | None = None
    result: list[ParsedQuestion] = []
    for block in _SEPARATOR.split(raw.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        while lines and _HEADER.match(lines[0]):
            category = lines.pop(0).lstrip("#").strip()
            while lines and not lines[0].strip():
                lines.pop(0)
        if not lines:
            continue
        text = _QUESTION_PREFIX.sub("", lines[0]).strip()
        answer = _ANSWER_PREFIX.sub("", "\n".join(lines[1:])).strip()
        if text:
            result.append(ParsedQuestion(category=category, text=text, answer=answer or None))
    return result
