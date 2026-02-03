#!/usr/bin/env python3
"""
Модуль для работы с OpenVPN Management Interface.

Предоставляет функциональность для получения списка активных клиентов
через Management Interface сокета OpenVPN.

Инварианты:
- M1.1: Создает модуль для работы с Management Interface
- M1.2: Не зависит от конкретного пути сокета (читает из конфигурации)
- M1.3: Возвращает Set[str] - множество CN активных клиентов
- M1.4: При недоступности сокета возвращает пустое множество (graceful degradation)
"""

import os
import sys
import socket
import logging
from pathlib import Path
from typing import Set, Optional

# Добавляем родительскую директорию в путь для импорта config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from collector.config import OPENVPN_DIR
except ImportError:
    # Fallback если config не загружен
    OPENVPN_DIR = os.getenv("OPENVPN_DIR", "/var/run/openvpn")

# ============================================================================
# Путь к Management Interface сокету
# M1.2: Читается из конфигурации, не захардкожен
# ============================================================================

# Путь к сокету Management Interface
MGMT_SOCKET_PATH = os.getenv(
    "OPENVPN_MGMT_SOCKET",
    os.path.join(OPENVPN_DIR, "mgmt.sock")
)

# ============================================================================
# Настройка логирования
# ============================================================================

logger = logging.getLogger(__name__)


def get_mgmt_socket_path() -> str:
    """
    Возвращает путь к Management Interface сокету.

    Returns:
        str: Путь к сокету из переменной окружения или конфигурации
    """
    return MGMT_SOCKET_PATH


def get_connected_clients(mgmt_socket_path: Optional[str] = None) -> Set[str]:
    """
    Получает список Common Names активных клиентов из Management Interface.

    Подключается к OpenVPN Management Interface и отправляет команду 'status 3'
    для получения списка активных клиентов. Парсит ответ и возвращает множество
    CN (Common Names) подключенных клиентов.

    Invariant M1.3: Возвращает Set[str] - множество CN активных клиентов
    Invariant M1.4: При недоступности сокета возвращает пустое множество

    Args:
        mgmt_socket_path: Опциональный путь к сокету.
                         Если None, используется значение из конфигурации (M1.2).

    Returns:
        Set[str]: Множество CN активных клиентов.
                  Пустое множество если сокет недоступен или нет клиентов.
    """
    # M1.2: Используем путь из конфигурации если не передан
    if mgmt_socket_path is None:
        mgmt_socket_path = get_mgmt_socket_path()

    logger.debug(f"Connecting to Management Interface socket: {mgmt_socket_path}")

    try:
        # Подключаемся к Unix-сокету Management Interface
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)  # Таймаут 5 секунд
        sock.connect(mgmt_socket_path)

        # Отправляем команду 'status 3' для получения списка клиентов
        # 'status 3' возвращает список клиентов в формате CLIENT_LIST
        sock.send(b"status 3\n")

        # Читаем ответ (небольшой буфер, достаточно для списка клиентов)
        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                # Проверяем завершение ответа (обычно заканчивается END)
                if b"END" in response:
                    break
            except socket.timeout:
                break

        sock.close()

        # Парсим ответ и извлекаем CN клиентов
        clients = parse_clients_from_response(response.decode('utf-8', errors='ignore'))

        logger.debug(f"Found {len(clients)} active clients: {clients}")
        return clients

    except (socket.error, OSError, IOError) as e:
        # M1.4: Graceful degradation - возвращаем пустое множество
        logger.warning(f"Cannot connect to Management Interface at {mgmt_socket_path}: {e}")
        return set()
    except Exception as e:
        # Любая другая ошибка также должна возвращать пустое множество
        logger.error(f"Unexpected error getting connected clients: {e}")
        return set()


def parse_clients_from_response(response: str) -> Set[str]:
    """
    Парсит ответ Management Interface и извлекает Common Names клиентов.

    Формат ответа команды 'status 3':
    CLIENT_LIST,Common Name,Real Address,Virtual Address,...

    Args:
        response: Текстовый ответ от Management Interface

    Returns:
        Set[str]: Множество CN клиентов
    """
    clients = set()

    for line in response.splitlines():
        # Ищем строки начинающиеся с "CLIENT_LIST,"
        # Формат: CLIENT_LIST,CN,Real Address,Virtual Address,...
        if line.startswith("CLIENT_LIST,"):
            parts = line.split(",")
            if len(parts) >= 2:
                cn = parts[1]
                if cn:  # Проверяем что CN не пустой
                    clients.add(cn)

    return clients


def get_connected_clients_count() -> int:
    """
    Возвращает количество активных клиентов.

    Удобная функция для получения только количества клиентов.

    Returns:
        int: Количество активных клиентов
    """
    clients = get_connected_clients()
    return len(clients)


def is_client_connected(cn: str, mgmt_socket_path: Optional[str] = None) -> bool:
    """
    Проверяет, подключен ли конкретный клиент.

    Args:
        cn: Common Name клиента для проверки
        mgmt_socket_path: Опциональный путь к сокету

    Returns:
        bool: True если клиент с данным CN активен
    """
    clients = get_connected_clients(mgmt_socket_path)
    return cn in clients


def main():
    """
    Точка входа для тестирования модуля.

    Выводит список активных клиентов в stdout.
    """
    import json

    clients = get_connected_clients()
    result = {
        "socket_path": get_mgmt_socket_path(),
        "client_count": len(clients),
        "clients": sorted(list(clients))
    }

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
