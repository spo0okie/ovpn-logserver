"""
Конфигурация путей для collector модулей.

Содержит настройки директорий для сертификатов, CRL и CCD файлов.
Приоритет настроек:
1. Переменные окружения (для Docker/тестов)
2. Файл config/openvpn.yaml (основная конфигурация)
3. Значения по умолчанию

Использует централизованную конфигурацию из core.config.
"""

import os
import sys

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Импортируем централизованную конфигурацию
try:
    from core.config import load_db_config, get_database_url, get_openvpn_paths
    # Загружаем пути из конфигурационного файла
    _openvpn_paths = get_openvpn_paths()
except Exception:
    # Fallback если core.config недоступен
    _openvpn_paths = {
        "base_dir": "/etc/openvpn",
        "certs_dir": "/etc/openvpn/certs",
        "cert_extension": ".crt",
        "crl_file": "/etc/openvpn/crl.pem",
        "ccd_dir": "/etc/openvpn/ccd",
        "management_socket": "/var/run/openvpn/mgmt.sock",
    }

# Базовая директория OpenVPN
# Приоритет: переменная окружения > config/openvpn.yaml > дефолт
OPENVPN_DIR = os.getenv(
    "OPENVPN_DIR",
    _openvpn_paths.get("base_dir", "/etc/openvpn")
)

# Директория с сертификатами клиентов (I6.1)
# Приоритет: переменная окружения > config/openvpn.yaml > дефолт
CERTS_DIR = os.getenv(
    "CERTS_DIR",
    _openvpn_paths.get("certs_dir", os.path.join(OPENVPN_DIR, "certs"))
)

# Путь к CRL файлу (I6.2)
# Приоритет: переменная окружения > config/openvpn.yaml > дефолт
CRL_FILE = os.getenv(
    "CRL_FILE",
    _openvpn_paths.get("crl_file", os.path.join(OPENVPN_DIR, "crl.pem"))
)

# Директория с CCD (Client Config Directory) файлами (I6.3)
# Приоритет: переменная окружения > config/openvpn.yaml > дефолт
CCD_DIR = os.getenv(
    "CCD_DIR",
    _openvpn_paths.get("ccd_dir", os.path.join(OPENVPN_DIR, "ccd"))
)

# Расширение файлов сертификатов (I6.1)
# Приоритет: переменная окружения > config/openvpn.yaml > дефолт
CERT_EXTENSION = os.getenv(
    "CERT_EXTENSION",
    _openvpn_paths.get("cert_extension", ".crt")
)

# Путь к Management Interface сокету OpenVPN (M1.2)
# Приоритет: переменная окружения > config/openvpn.yaml > дефолт
MGMT_SOCKET_PATH = os.getenv(
    "OPENVPN_MGMT_SOCKET",
    _openvpn_paths.get("management_socket", "/var/run/openvpn/mgmt.sock")
)


def get_config_summary():
    """
    Возвращает сводку конфигурации для логирования.

    Returns:
        dict: Словарь с текущими путями конфигурации
    """
    return {
        "openvpn_dir": OPENVPN_DIR,
        "certs_dir": CERTS_DIR,
        "crl_file": CRL_FILE,
        "ccd_dir": CCD_DIR,
        "cert_extension": CERT_EXTENSION,
        "mgmt_socket_path": MGMT_SOCKET_PATH,
    }


def get_db_config_summary():
    """
    Возвращает сводку конфигурации БД (без пароля).

    Returns:
        dict: Словарь с параметрами подключения к БД
    """
    try:
        from core.config import load_db_config
        cfg = load_db_config()
        return {
            "host": cfg.get("host", "localhost"),
            "port": cfg.get("port", 3306),
            "name": cfg.get("name", "openvpn_logs"),
            "user": cfg.get("user", "openvpn_user"),
            "pool_size": cfg.get("pool_size", 10),
            "max_overflow": cfg.get("max_overflow", 20),
        }
    except Exception:
        # Fallback если конфиг не загружен
        return {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "3306")),
            "name": os.getenv("DB_NAME", "openvpn_logs"),
            "user": os.getenv("DB_USER", "openvpn_user"),
            "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        }
