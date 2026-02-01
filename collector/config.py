"""
Конфигурация путей для collector модулей.

Содержит настройки директорий для сертификатов, CRL и CCD файлов.
Все пути могут быть переопределены через переменные окружения.
"""

import os

# Базовая директория OpenVPN (может быть переопределена через OPENVPN_DIR)
OPENVPN_DIR = os.getenv(
    "OPENVPN_DIR",
    "/etc/openvpn"
)

# Директория с сертификатами клиентов (I6.1)
# По умолчанию: /etc/openvpn/certs или переопределяется через CERTS_DIR
CERTS_DIR = os.getenv(
    "CERTS_DIR",
    os.path.join(OPENVPN_DIR, "certs")
)

# Путь к CRL файлу (I6.2)
# По умолчанию: /etc/openvpn/crl.pem или переопределяется через CRL_FILE
CRL_FILE = os.getenv(
    "CRL_FILE",
    os.path.join(OPENVPN_DIR, "crl.pem")
)

# Директория с CCD (Client Config Directory) файлами (I6.3)
# По умолчанию: /etc/openvpn/ccd или переопределяется через CCD_DIR
CCD_DIR = os.getenv(
    "CCD_DIR",
    os.path.join(OPENVPN_DIR, "ccd")
)

# Расширение файлов сертификатов (I6.1)
CERT_EXTENSION = os.getenv(
    "CERT_EXTENSION",
    ".crt"
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
    }
