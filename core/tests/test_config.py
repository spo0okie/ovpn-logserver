"""
Тесты core.config: сборка DATABASE_URL, поддержка unix_socket, ENV-override.
"""

import os

import pytest

import core.config as config_module
from core.config import (
    ConfigError,
    get_database_url,
    get_database_url_safe,
    load_db_config,
    reload_config,
)

DB_ENV_VARS = [
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_UNIX_SOCKET",
    "DB_CHARSET",
]


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """
    Изолированная конфигурация: чистые ENV, CONFIG_DIR во временной директории.

    Возвращает функцию записи database.yaml из словаря настроек.
    """
    for var in DB_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config_module, "CONFIG_DIR", str(tmp_path))
    reload_config()

    def write_db_yaml(settings: dict) -> None:
        lines = ["database:"]
        for key, value in settings.items():
            lines.append(f"  {key}: {value}")
        (tmp_path / "database.yaml").write_text("\n".join(lines), encoding="utf-8")
        reload_config()

    yield write_db_yaml
    reload_config()


BASE_SETTINGS = {
    "host": "localhost",
    "port": 3306,
    "name": "openvpn_logs",
    "user": "ovpn",
    "password": "secret",
}


def test_url_without_socket_has_no_query(config_dir):
    config_dir(BASE_SETTINGS)
    assert get_database_url() == "mysql+pymysql://ovpn:secret@localhost:3306/openvpn_logs"


def test_unix_socket_from_yaml_appended_to_url(config_dir):
    config_dir({**BASE_SETTINGS, "unix_socket": "/var/run/mysqld/mysqld.sock"})
    assert get_database_url() == (
        "mysql+pymysql://ovpn:secret@localhost:3306/openvpn_logs"
        "?unix_socket=/var/run/mysqld/mysqld.sock"
    )


def test_env_overrides_yaml_socket(config_dir, monkeypatch):
    config_dir({**BASE_SETTINGS, "unix_socket": "/from/yaml.sock"})
    monkeypatch.setenv("DB_UNIX_SOCKET", "/from/env.sock")
    reload_config()
    assert get_database_url().endswith("?unix_socket=/from/env.sock")


def test_socket_allows_missing_host(config_dir):
    settings = {k: v for k, v in BASE_SETTINGS.items() if k != "host"}
    config_dir({**settings, "unix_socket": "/var/run/mysqld/mysqld.sock"})
    cfg = load_db_config()
    assert cfg["host"] == "localhost"


def test_missing_host_without_socket_fails(config_dir):
    settings = {k: v for k, v in BASE_SETTINGS.items() if k != "host"}
    config_dir(settings)
    with pytest.raises(ConfigError, match="host"):
        load_db_config()


def test_safe_url_masks_password_and_keeps_socket(config_dir):
    config_dir({**BASE_SETTINGS, "unix_socket": "/var/run/mysqld/mysqld.sock"})
    safe = get_database_url_safe()
    assert "secret" not in safe
    assert "****" in safe
    assert safe.endswith("?unix_socket=/var/run/mysqld/mysqld.sock")


def test_database_url_env_wins_over_everything(config_dir, monkeypatch):
    config_dir({**BASE_SETTINGS, "unix_socket": "/var/run/mysqld/mysqld.sock"})
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./override.db")
    assert get_database_url() == "sqlite:///./override.db"
