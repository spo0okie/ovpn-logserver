"""
Централизованная конфигурация системы.

Загружает настройки из config/*.yaml и применяет ENV override.
Если YAML-файл с обязательными настройками не найден или содержит
заглушки, приложение аварийно завершает работу — fallback на
захардкоженные пароли запрещён.

Поддерживаемые ENV-переменные:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_UNIX_SOCKET,
    DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE, DB_CHARSET
    DATABASE_URL                       — переопределяет всё подключение целиком
    WEB_AUTH_USERNAME, WEB_AUTH_PASSWORD, WEB_AUTH_PASSWORD_HASH
    OPENVPN_BASE_DIR, OPENVPN_CERTS_DIR, OPENVPN_CERT_EXTENSION,
    OPENVPN_CRL_FILE, OPENVPN_CCD_DIR, OPENVPN_MGMT_SOCKET
"""

import os
from functools import lru_cache
from typing import Dict, Any, Optional
from urllib.parse import quote, quote_plus

import yaml

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


class ConfigError(RuntimeError):
    """Конфигурация невалидна или отсутствует."""


def _load_yaml(filename: str, root_key: str, required: bool) -> Dict[str, Any]:
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        if required:
            raise ConfigError(
                f"Configuration file not found: {path}. "
                f"Скопируйте {filename}.example в {filename} и заполните значения."
            )
        return {}

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if root_key not in cfg:
        if required:
            raise ConfigError(f"Invalid configuration {path}: '{root_key}' section not found")
        return {}
    return cfg[root_key] or {}


def _env_int(name: str, default: Optional[int]) -> Optional[int]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"ENV {name}={value!r} must be integer") from exc


@lru_cache()
def load_db_config() -> Dict[str, Any]:
    """Загружает конфигурацию БД из YAML и применяет ENV-override.

    Файл database.yaml не обязателен: если все значения заданы через ENV
    (DB_NAME/DB_USER/DB_PASSWORD/host-или-DB_UNIX_SOCKET), конфиг валиден и
    без файла. Отсутствие обязательных значений в обоих источниках приводит
    к ConfigError ниже.
    """
    cfg = _load_yaml("database.yaml", "database", required=False)

    merged = {
        "host": os.getenv("DB_HOST") or cfg.get("host"),
        "port": _env_int("DB_PORT", cfg.get("port", 3306)),
        "name": os.getenv("DB_NAME") or cfg.get("name"),
        "user": os.getenv("DB_USER") or cfg.get("user"),
        "password": os.getenv("DB_PASSWORD", cfg.get("password")),
        "pool_size": _env_int("DB_POOL_SIZE", cfg.get("pool_size", 10)),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", cfg.get("max_overflow", 20)),
        "pool_timeout": _env_int("DB_POOL_TIMEOUT", cfg.get("pool_timeout", 30)),
        "pool_recycle": _env_int("DB_POOL_RECYCLE", cfg.get("pool_recycle", 3600)),
        "charset": os.getenv("DB_CHARSET") or cfg.get("charset", "utf8mb4"),
        "unix_socket": os.getenv("DB_UNIX_SOCKET") or cfg.get("unix_socket"),
    }

    for key in ("name", "user", "password"):
        if not merged[key]:
            raise ConfigError(
                f"Database config: '{key}' is empty. "
                "Заполните config/database.yaml или задайте ENV."
            )

    if not merged["host"]:
        if merged["unix_socket"]:
            # PyMySQL при unix_socket игнорирует host, но URL требует непустой hostname
            merged["host"] = "localhost"
        else:
            raise ConfigError(
                "Database config: 'host' is empty. "
                "Заполните config/database.yaml или задайте ENV."
            )

    return merged


@lru_cache()
def load_auth_config() -> Dict[str, Any]:
    """Загружает auth-конфигурацию из YAML и применяет ENV-override.

    Файл auth.yaml не обязателен, если username и password/password_hash
    заданы через ENV (WEB_AUTH_*). Иначе — ConfigError ниже.
    """
    cfg = _load_yaml("auth.yaml", "auth", required=False)
    web = cfg.get("web", {}) or {}

    username = os.getenv("WEB_AUTH_USERNAME") or web.get("username")
    password = os.getenv("WEB_AUTH_PASSWORD", web.get("password"))
    password_hash = os.getenv("WEB_AUTH_PASSWORD_HASH") or web.get("password_hash")

    if not username:
        raise ConfigError("Auth config: web.username is required")
    if not password and not password_hash:
        raise ConfigError(
            "Auth config: either web.password_hash (recommended) "
            "or web.password must be set"
        )

    return {
        "web": {
            "username": username,
            "password": password,
            "password_hash": password_hash,
        }
    }


@lru_cache()
def load_openvpn_config() -> Dict[str, Any]:
    """Загружает OpenVPN-конфиг (пути не секретны → дефолты допустимы)."""
    cfg = _load_yaml("openvpn.yaml", "openvpn", required=False)
    return {
        "base_dir": os.getenv("OPENVPN_BASE_DIR") or cfg.get("base_dir", "/etc/openvpn"),
        "certs_dir": os.getenv("OPENVPN_CERTS_DIR") or cfg.get("certs_dir", "/etc/openvpn/certs"),
        "cert_extension": os.getenv("OPENVPN_CERT_EXTENSION") or cfg.get("cert_extension", ".crt"),
        "crl_file": os.getenv("OPENVPN_CRL_FILE") or cfg.get("crl_file", "/etc/openvpn/crl.pem"),
        "ccd_dir": os.getenv("OPENVPN_CCD_DIR") or cfg.get("ccd_dir", "/etc/openvpn/ccd"),
        "management_socket": (
            os.getenv("OPENVPN_MGMT_SOCKET") or cfg.get("management_socket", "/var/run/openvpn/mgmt.sock")
        ),
    }


def get_database_url() -> str:
    """Полный DATABASE_URL для SQLAlchemy. ENV `DATABASE_URL` имеет приоритет."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    cfg = load_db_config()
    url = (
        f"mysql+pymysql://{quote_plus(cfg['user'])}:{quote_plus(cfg['password'])}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['name']}"
    )
    if cfg.get("unix_socket"):
        # safe='/' сохраняет путь читаемым, но экранирует пробелы/спецсимволы
        url += f"?unix_socket={quote(cfg['unix_socket'], safe='/')}"
    return url


def get_database_url_safe() -> str:
    """DATABASE_URL с замаскированным паролем (для логов)."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        # Маскируем пароль в формате mysql+pymysql://user:pass@host/db
        import re
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", env_url)
    cfg = load_db_config()
    url = (
        f"mysql+pymysql://{cfg['user']}:****"
        f"@{cfg['host']}:{cfg['port']}/{cfg['name']}"
    )
    if cfg.get("unix_socket"):
        url += f"?unix_socket={cfg['unix_socket']}"
    return url


def get_engine_kwargs() -> Dict[str, Any]:
    """Параметры для создания SQLAlchemy engine.

    Если подключение задано целиком через ENV `DATABASE_URL`, конфиг
    database.yaml не требуется — параметры пула берутся из ENV с дефолтами.
    """
    url = get_database_url()

    if os.getenv("DATABASE_URL"):
        kwargs: Dict[str, Any] = {
            "pool_pre_ping": True,
            "echo": False,
            "pool_size": _env_int("DB_POOL_SIZE", 10),
            "max_overflow": _env_int("DB_MAX_OVERFLOW", 20),
            "pool_timeout": _env_int("DB_POOL_TIMEOUT", 30),
            "pool_recycle": _env_int("DB_POOL_RECYCLE", 3600),
        }
        if "mysql" in url:
            kwargs["connect_args"] = {"charset": os.getenv("DB_CHARSET") or "utf8mb4"}
        return kwargs

    cfg = load_db_config()
    kwargs = {
        "pool_pre_ping": True,
        "echo": False,
        "pool_size": cfg["pool_size"],
        "max_overflow": cfg["max_overflow"],
        "pool_timeout": cfg["pool_timeout"],
        "pool_recycle": cfg["pool_recycle"],
    }
    if "mysql" in url:
        kwargs["connect_args"] = {"charset": cfg["charset"]}
    return kwargs


def get_web_auth_credentials() -> Dict[str, Optional[str]]:
    """Возвращает auth-настройки web: username и password/password_hash."""
    return load_auth_config()["web"]


def get_openvpn_paths() -> Dict[str, str]:
    """Возвращает пути и настройки OpenVPN."""
    return load_openvpn_config()


def reload_config() -> None:
    """Сбрасывает кеш конфигурации (для тестов и горячей перезагрузки)."""
    load_db_config.cache_clear()
    load_auth_config.cache_clear()
    load_openvpn_config.cache_clear()
