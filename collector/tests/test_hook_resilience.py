"""
Инвариант I4.5 / I5.5: хуки client-connect/disconnect НИКОГДА не должны
завершаться с ненулевым кодом, даже если импорт зависимостей (core.database,
core.config) падает на этапе загрузки модуля.

Ненулевой exit из client-connect заставляет OpenVPN отклонить подключение
клиента — то есть сломанный конфиг/права БД заблокировали бы весь VPN.
Тест запускает хук как отдельный процесс с заведомо невалидной конфигурацией,
которая роняет core.config на импорт-этапе, и требует exit 0.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECT = REPO_ROOT / "collector" / "client_connect.py"
DISCONNECT = REPO_ROOT / "collector" / "client_disconnect.py"


def _broken_config_env() -> dict:
    """ENV, при котором core.config падает с ConfigError на импорт-этапе.

    DATABASE_URL снят (иначе engine-конфиг не читает yaml), а DB_POOL_SIZE
    задан нечисловым — _env_int() кидает ConfigError внутри load_db_config(),
    вызываемого при импорте core.database.
    """
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["DB_POOL_SIZE"] = "not-a-number"
    # Гарантируем, что обязательные значения не «спасут» конфиг из ENV:
    # ломается именно парсинг пула, до подключения дело не доходит.
    return env


@pytest.mark.parametrize("script", [CONNECT, DISCONNECT], ids=["connect", "disconnect"])
def test_hook_exits_zero_on_import_failure(script: Path):
    result = subprocess.run(
        [sys.executable, str(script)],
        env=_broken_config_env(),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"{script.name} вернул {result.returncode} при сломанном конфиге — "
        f"это заблокировало бы VPN.\nstderr:\n{result.stderr}"
    )
    # Убеждаемся, что задействован именно путь сбоя импорта, а не «повезло»
    assert "DB_POOL_SIZE" in result.stderr or "ошибка импорта" in result.stderr, (
        "Ожидался лог о сбое импорта зависимостей; тест не проверяет нужный путь.\n"
        f"stderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("script", [CONNECT, DISCONNECT], ids=["connect", "disconnect"])
def test_hook_exits_zero_without_openvpn_env(script: Path):
    """Без переменных OpenVPN (common_name и т.п.) хук тоже отдаёт exit 0."""
    env = dict(os.environ)
    env.pop("common_name", None)
    env.pop("trusted_ip", None)
    result = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"{script.name} вернул {result.returncode} без OpenVPN-переменных.\n"
        f"stderr:\n{result.stderr}"
    )
