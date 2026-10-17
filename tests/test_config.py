import pytest

from bot.config import ConfigError, load_settings


def test_load_settings_parses_admin_ids_and_defaults():
    s = load_settings({"BOT_TOKEN": "123:abc", "ADMIN_IDS": " 111, 222 ,,"})
    assert s.bot_token == "123:abc"
    assert s.admin_ids == frozenset({111, 222})
    assert s.db_path == "data/bot.db"
    assert s.groq_model == "openai/gpt-oss-120b"
    assert s.grader == ""


def test_load_settings_requires_token():
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        load_settings({})


def test_load_settings_rejects_bad_admin_id():
    with pytest.raises(ConfigError, match="ADMIN_IDS"):
        load_settings({"BOT_TOKEN": "t", "ADMIN_IDS": "@dan"})
