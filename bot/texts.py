from html import escape

TELEGRAM_LIMIT = 4096
# Raw text is split before HTML escaping, which can make it longer.
_CHUNK = 3000


def split_text(text: str, limit: int = _CHUNK) -> list[str]:
    """Splits text into pieces of at most `limit` chars, preferring line and word boundaries."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    if text or not chunks:
        chunks.append(text)
    return chunks


def titled_chunks(title_html: str, body: str) -> list[str]:
    """HTML messages: a bold title on the first one, the escaped body split across as many as needed."""
    parts = split_text(body)
    return [f"{title_html}\n{escape(parts[0])}"] + [escape(p) for p in parts[1:]]


def short(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"
