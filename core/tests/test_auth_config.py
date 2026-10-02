"""
Тесты core.config.load_auth_config: несколько пользователей web/API.

Список auth.web.users плюс legacy-пара auth.web.username/password_hash
(её же перекрывают ENV WEB_AUTH_*), проверки на пустой набор и дубли.
"""

import pytest

import core.config as config_module
from core.config import ConfigError, get_web_users, reload_config

AUTH_ENV_VARS = ["WEB_AUTH_USERNAME", "WEB_AUTH_PASSWORD", "WEB_AUTH_PASSWORD_HASH"]


@pytest.fixture
def auth_yaml(tmp_path, monkeypatch):
    """Чистые ENV, CONFIG_DIR во временной директории; возвращает запись auth.yaml."""
    for var in AUTH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config_module, "CONFIG_DIR", str(tmp_path))
    reload_config()

    def write(text: str) -> None:
        (tmp_path / "auth.yaml").write_text(text, encoding="utf-8")
        reload_config()

    yield write
    reload_config()


def _names(users):
    return [u["username"] for u in users]


def test_legacy_single_user(auth_yaml):
    auth_yaml("auth:\n  web:\n    username: admin\n    password_hash: H1\n")
    assert get_web_users() == [{"username": "admin", "password": None, "password_hash": "H1"}]


def test_users_list_plus_legacy_pair(auth_yaml):
    auth_yaml(
        "auth:\n"
        "  web:\n"
        "    username: admin\n"
        "    password_hash: H1\n"
        "    users:\n"
        "      - username: arms\n"
        "        password_hash: H2\n"
        "      - username: auditor\n"
        "        password: plain\n"
    )
    users = get_web_users()
    assert _names(users) == ["admin", "arms", "auditor"]
    assert users[1]["password_hash"] == "H2"
    assert users[2]["password"] == "plain"


def test_users_list_only(auth_yaml):
    auth_yaml("auth:\n  web:\n    users:\n      - username: arms\n        password_hash: H2\n")
    assert _names(get_web_users()) == ["arms"]


def test_env_overrides_legacy_pair_and_keeps_list(auth_yaml, monkeypatch):
    """ENV, как и раньше, перекрывает legacy-пару; список из YAML остаётся."""
    monkeypatch.setenv("WEB_AUTH_USERNAME", "root")
    monkeypatch.setenv("WEB_AUTH_PASSWORD_HASH", "ENVHASH")
    auth_yaml(
        "auth:\n"
        "  web:\n"
        "    username: admin\n"
        "    password_hash: H1\n"
        "    users:\n"
        "      - username: arms\n"
        "        password_hash: H2\n"
    )
    users = get_web_users()
    assert _names(users) == ["root", "arms"]
    assert users[0]["password_hash"] == "ENVHASH"


def test_env_only_without_yaml(auth_yaml, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_USERNAME", "admin")
    monkeypatch.setenv("WEB_AUTH_PASSWORD", "pw")
    reload_config()
    assert get_web_users() == [{"username": "admin", "password": "pw", "password_hash": None}]


def test_no_users_is_error(auth_yaml):
    auth_yaml("auth:\n  web: {}\n")
    with pytest.raises(ConfigError, match="no users"):
        get_web_users()


def test_duplicate_username_is_error(auth_yaml):
    auth_yaml(
        "auth:\n"
        "  web:\n"
        "    username: admin\n"
        "    password_hash: H1\n"
        "    users:\n"
        "      - username: admin\n"
        "        password_hash: H2\n"
    )
    with pytest.raises(ConfigError, match="duplicate"):
        get_web_users()


def test_list_user_without_password_is_error(auth_yaml):
    auth_yaml("auth:\n  web:\n    users:\n      - username: arms\n")
    with pytest.raises(ConfigError, match=r"web.users\[0\].*arms"):
        get_web_users()


def test_list_user_without_username_is_error(auth_yaml):
    auth_yaml("auth:\n  web:\n    users:\n      - password_hash: H2\n")
    with pytest.raises(ConfigError, match="username is required"):
        get_web_users()


def test_users_must_be_list(auth_yaml):
    auth_yaml("auth:\n  web:\n    users:\n      arms: H2\n")
    with pytest.raises(ConfigError, match="must be a list"):
        get_web_users()
