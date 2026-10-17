import os
from dataclasses import dataclass
from typing import Mapping


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: str = "data/bot.db"
    # groq, openai or heuristic. Empty: Groq if GROQ_API_KEY is set, otherwise heuristic.
    grader: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""


def _admin_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.lstrip("-").isdigit():
            raise ConfigError(f"ADMIN_IDS: «{part}» не похоже на числовой Telegram ID (узнать свой ID: команда /id в боте)")
        ids.add(int(part))
    return frozenset(ids)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    token = env.get("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("Не задан BOT_TOKEN в .env (токен выдаёт @BotFather)")
    return Settings(
        bot_token=token,
        admin_ids=_admin_ids(env.get("ADMIN_IDS", "")),
        db_path=env.get("DB_PATH", "").strip() or "data/bot.db",
        grader=env.get("GRADER", "").strip().lower(),
        groq_api_key=env.get("GROQ_API_KEY", "").strip(),
        groq_model=env.get("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b",
        llm_base_url=env.get("LLM_BASE_URL", "").strip(),
        llm_api_key=env.get("LLM_API_KEY", "").strip(),
        llm_model=env.get("LLM_MODEL", "").strip(),
    )
