#!/usr/bin/env python3
"""
Модуль для работы с OpenVPN Management Interface.

Получает множество CN активных клиентов через unix-сокет.

Инварианты:
- M1.1: Самостоятельный модуль с тестами.
- M1.2: Путь к сокету берётся из конфигурации (не захардкожен в функции).
- M1.3: Возвращает Set[str] — CN активных клиентов.
- M1.4: При ошибке сокета возвращает пустое множество.

Реализация парсит ответ команды `status 3`, в которой поля разделены символом
табуляции. Команда `quit` отправляется до закрытия сокета.
"""

import logging
import os
import socket
import sys
from typing import Optional, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from collector.config import OPENVPN_DIR, MGMT_SOCKET_PATH
except ImportError:
    OPENVPN_DIR = os.getenv("OPENVPN_DIR", "/var/run/openvpn")
    MGMT_SOCKET_PATH = os.getenv(
        "OPENVPN_MGMT_SOCKET",
        os.path.join(OPENVPN_DIR, "mgmt.sock"),
    )

logger = logging.getLogger(__name__)

_RECV_TIMEOUT_SECONDS = 5.0
_END_MARKERS = (b"\nEND\n", b"\nEND\r\n", b"\r\nEND\r\n")
_SKIP_PREFIXES = (
    "TITLE",
    "TIME",
    "HEADER",
    "GLOBAL_STATS",
    "ROUTING_TABLE",
    "END",
    ">",
    "OpenVPN",
)


def get_mgmt_socket_path() -> str:
    """Возвращает путь к Management Interface сокету (M1.2)."""
    return MGMT_SOCKET_PATH


def get_connected_clients(mgmt_socket_path: Optional[str] = None) -> Set[str]:
    """Возвращает множество CN активных клиентов (M1.3, M1.4)."""
    if mgmt_socket_path is None:
        mgmt_socket_path = get_mgmt_socket_path()

    if not os.path.exists(mgmt_socket_path):
        logger.error("Management Interface socket not found: %s", mgmt_socket_path)
        return set()

    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(_RECV_TIMEOUT_SECONDS)
        sock.connect(mgmt_socket_path)

        sock.sendall(b"status 3\n")
        response = _recv_until_end(sock)

        try:
            sock.sendall(b"quit\n")
        except OSError:
            pass

        text = response.decode("utf-8", errors="ignore")
        clients = parse_clients_from_response(text)
        logger.info("MGMT: %d active clients", len(clients))
        if clients:
            logger.debug("Active clients: %s", clients)
        return clients

    except (socket.error, OSError, IOError) as exc:
        logger.error("Cannot read from Management Interface at %s: %s", mgmt_socket_path, exc)
        return set()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected MGMT error: %s", exc)
        return set()
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _recv_until_end(sock: socket.socket, max_bytes: int = 1024 * 1024) -> bytes:
    """Читает из сокета до маркера '\\nEND\\n' или таймаута."""
    buf = b""
    while len(buf) < max_bytes:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            logger.debug("MGMT recv timeout")
            break
        if not chunk:
            break
        buf += chunk
        if any(marker in buf for marker in _END_MARKERS):
            break
    return buf


def parse_clients_from_response(response: str) -> Set[str]:
    """
    Парсит ответ команды `status 3` (табуляция-разделённый).

    Формат строки клиента:
        CLIENT_LIST<TAB>Common Name<TAB>Real Address<TAB>...
    Поскольку CN может содержать пробелы, разбиваем строго по `\\t`.
    Заголовок `HEADER\\tCLIENT_LIST\\t...` пропускается.
    """
    clients: Set[str] = set()
    for raw_line in response.splitlines():
        line = raw_line.strip("\r\n")
        if not line:
            continue
        # Пропускаем строки, которые точно не содержат CLIENT_LIST.
        if any(line.startswith(p) for p in _SKIP_PREFIXES):
            continue
        if "\t" not in line:
            # Не tab-separated — нечего парсить (возможен `>INFO:` и т.п.).
            continue

        parts = line.split("\t")
        if parts[0] != "CLIENT_LIST" or len(parts) < 2:
            continue
        cn = parts[1].strip()
        if cn and cn != "Common Name":  # на всякий случай отсеять заголовок
            clients.add(cn)
    return clients


def get_connected_clients_count() -> int:
    return len(get_connected_clients())


def is_client_connected(cn: str, mgmt_socket_path: Optional[str] = None) -> bool:
    return cn in get_connected_clients(mgmt_socket_path)


def main():
    import json

    clients = get_connected_clients()
    print(
        json.dumps(
            {
                "socket_path": get_mgmt_socket_path(),
                "client_count": len(clients),
                "clients": sorted(clients),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
