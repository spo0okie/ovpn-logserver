"""
Централизованная конфигурация системы.

Загружает настройки из config/database.yaml и config/auth.yaml.
Предоставляет единый источник конфигурации для всех компонентов.
Все настройки хранятся в YML файлах, без использования переменных окружения.
"""

import os
from functools import lru_cache
from typing import Dict, Any, Optional

# Путь к директории конфигурации
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


@lru_cache()
def load_db_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию БД из YAML файла.
    
    Результат кэшируется для повторного использования.
    
    Returns:
        Dict[str, Any]: Конфигурация базы данных
    
    Raises:
        FileNotFoundError: Если файл конфигурации не найден
        ValueError: Если конфигурация некорректна
    """
    try:
        import yaml
        config_path = os.path.join(CONFIG_DIR, "database.yaml")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        if not config or "database" not in config:
            raise ValueError("Invalid configuration: 'database' section not found")
        
        return config["database"]
        
    except ImportError:
        # Fallback: если yaml не установлен, используем значения по умолчанию
        return _get_default_db_config()


@lru_cache()
def load_auth_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию аутентификации из YAML файла.
    
    Результат кэшируется для повторного использования.
    
    Returns:
        Dict[str, Any]: Конфигурация аутентификации
    
    Raises:
        FileNotFoundError: Если файл конфигурации не найден
        ValueError: Если конфигурация некорректна
    """
    try:
        import yaml
        config_path = os.path.join(CONFIG_DIR, "auth.yaml")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Auth configuration file not found: {config_path}")
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        if not config or "auth" not in config:
            raise ValueError("Invalid configuration: 'auth' section not found")
        
        return config["auth"]
        
    except ImportError:
        # Fallback: если yaml не установлен, используем значения по умолчанию
        return _get_default_auth_config()


def _get_default_db_config() -> Dict[str, Any]:
    """
    Возвращает конфигурацию БД по умолчанию.
    
    Используется как fallback когда YAML не доступен.
    
    Returns:
        Dict[str, Any]: Конфигурация по умолчанию
    """
    return {
        "host": "localhost",
        "port": 3306,
        "name": "openvpn_logs",
        "user": "openvpn_user",
        "password": "REDACTED_DB_PASSWORD",
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 3600,
        "charset": "utf8mb4",
    }


def _get_default_auth_config() -> Dict[str, Any]:
    """
    Возвращает конфигурацию аутентификации по умолчанию.
    
    Используется как fallback когда YAML не доступен.
    
    Returns:
        Dict[str, Any]: Конфигурация по умолчанию
    """
    return {
        "web": {
            "username": "admin",
            "password": "admin_password_123"
        }
    }


def get_database_url() -> str:
    """
    Возвращает DATABASE_URL для SQLAlchemy.
    
    Формирует URL из параметров конфигурации.
    
    Returns:
        str: DATABASE_URL в формате mysql+pymysql://user:password@host:port/database
    """
    cfg = load_db_config()
    return (
        f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['name']}"
    )


def get_database_url_safe() -> str:
    """
    Возвращает DATABASE_URL без пароля (для логирования).
    
    Returns:
        str: DATABASE_URL с замаскированным паролем
    """
    cfg = load_db_config()
    return (
        f"mysql+pymysql://{cfg['user']}:****"
        f"@{cfg['host']}:{cfg['port']}/{cfg['name']}"
    )


def get_engine_kwargs() -> Dict[str, Any]:
    """
    Возвращает параметры для создания SQLAlchemy engine.
    
    Returns:
        Dict[str, Any]: Параметры для create_engine()
    """
    cfg = load_db_config()
    
    kwargs = {
        "pool_pre_ping": True,
        "echo": False,
        "pool_size": cfg.get("pool_size", 10),
        "max_overflow": cfg.get("max_overflow", 20),
        "pool_timeout": cfg.get("pool_timeout", 30),
        "pool_recycle": cfg.get("pool_recycle", 3600),
    }
    
    # Добавляем connect_args для MySQL
    database_url = get_database_url()
    if "mysql" in database_url:
        kwargs["connect_args"] = {
            "charset": cfg.get("charset", "utf8mb4")
        }
    
    return kwargs


def get_web_auth_credentials() -> Dict[str, str]:
    """
    Возвращает учетные данные для Web аутентификации.
    
    Returns:
        Dict[str, str]: Словарь с username и password
    """
    cfg = load_auth_config()
    web_auth = cfg.get("web", {})
    return {
        "username": web_auth.get("username", "admin"),
        "password": web_auth.get("password", "admin_password_123")
    }


def reload_config() -> Dict[str, Any]:
    """
    Принудительно перезагружает конфигурацию (сбрасывает кэш).
    
    Returns:
        Dict[str, Any]: Перезагруженная конфигурация БД
    """
    load_db_config.cache_clear()
    load_auth_config.cache_clear()
    load_openvpn_config.cache_clear()
    return load_db_config()


@lru_cache()
def load_openvpn_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию OpenVPN из YAML файла.
    
    Результат кэшируется для повторного использования.
    
    Returns:
        Dict[str, Any]: Конфигурация OpenVPN путей
    
    Raises:
        FileNotFoundError: Если файл конфигурации не найден
        ValueError: Если конфигурация некорректна
    """
    try:
        import yaml
        config_path = os.path.join(CONFIG_DIR, "openvpn.yaml")
        
        if not os.path.exists(config_path):
            # Возвращаем дефолтную конфигурацию если файл не найден
            return _get_default_openvpn_config()
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        if not config or "openvpn" not in config:
            return _get_default_openvpn_config()
        
        return config["openvpn"]
        
    except ImportError:
        # Fallback: если yaml не установлен, используем значения по умолчанию
        return _get_default_openvpn_config()


def _get_default_openvpn_config() -> Dict[str, Any]:
    """
    Возвращает конфигурацию OpenVPN по умолчанию.
    
    Используется как fallback когда YAML не доступен или файл не найден.
    
    Returns:
        Dict[str, Any]: Конфигурация по умолчанию
    """
    return {
        "base_dir": "/etc/openvpn",
        "certs_dir": "/etc/openvpn/certs",
        "cert_extension": ".crt",
        "crl_file": "/etc/openvpn/crl.pem",
        "ccd_dir": "/etc/openvpn/ccd",
        "management_socket": "/var/run/openvpn/mgmt.sock",
    }


def get_openvpn_paths() -> Dict[str, str]:
    """
    Возвращает пути к файлам и директориям OpenVPN.
    
    Returns:
        Dict[str, str]: Словарь с путями:
            - base_dir: базовая директория OpenVPN
            - certs_dir: директория с сертификатами
            - cert_extension: расширение файлов сертификатов
            - crl_file: путь к CRL файлу
            - ccd_dir: директория с CCD файлами
            - management_socket: путь к Management Interface сокету
    """
    cfg = load_openvpn_config()
    return {
        "base_dir": cfg.get("base_dir", "/etc/openvpn"),
        "certs_dir": cfg.get("certs_dir", "/etc/openvpn/certs"),
        "cert_extension": cfg.get("cert_extension", ".crt"),
        "crl_file": cfg.get("crl_file", "/etc/openvpn/crl.pem"),
        "ccd_dir": cfg.get("ccd_dir", "/etc/openvpn/ccd"),
        "management_socket": cfg.get("management_socket", "/var/run/openvpn/mgmt.sock"),
    }
