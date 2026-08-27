#!/usr/bin/env python3
"""
Скрипт client-disconnect для OpenVPN.

Обрабатывает событие отключения клиента:
1. Читает переменные окружения от OpenVPN (I5.1)
2. Находит последнюю активную сессию по CN (I5.1)
3. Устанавливает disconnected_at = NOW() (I5.2)
4. Меняет статус на 'closed' (I5.3)
5. Сохраняет bytes_sent/bytes_received (I5.4)
6. При любой ошибке возвращает exit 0 (I5.5)
7. Только UPDATE операции, никаких INSERT (I5.6)

Инварианты:
- I5.1: Обновляет только последнюю активную сессию по CN
- I5.2: Устанавливает disconnected_at = NOW()
- I5.3: Меняет статус на 'closed'
- I5.4: Сохраняет bytes_sent/bytes_received
- I5.5: exit 0 при любой ошибке
- I5.6: Только UPDATE операции
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Инвариант I5.5: хук не должен падать на импорт-этапе (см. client_connect.py).
try:
    from sqlalchemy import or_
    from core.time import utcnow
    from core.database import SessionLocal, engine
    from core.models import Account, Session, Base
    from collector.config import SERVER_NAME
    from collector.server_registry import resolve_server_id
    _IMPORT_ERROR = None
except Exception as _import_exc:  # noqa: BLE001 — сознательно ловим всё
    _IMPORT_ERROR = _import_exc
    or_ = None
    SessionLocal = engine = None
    Account = Session = Base = None
    SERVER_NAME = None
    resolve_server_id = None

# =============================================================================
# Настройка логирования
# =============================================================================

# Создаем директорию для логов если её нет
LOG_DIR = Path("/var/log/openvpn-logserver")
if not LOG_DIR.exists():
    # Fallback для тестов - используем текущую директорию
    LOG_DIR = Path(__file__).parent.parent / "logs"
    try:
        LOG_DIR.mkdir(exist_ok=True)
    except Exception:
        pass

LOG_FILE = LOG_DIR / "client-disconnect.log"

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Форматтер для логов
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Обработчик для записи в файл (если доступен)
try:
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except (PermissionError, OSError) as e:
    # Если нет прав на запись в файл - используем только stderr
    print(f"Warning: Cannot write to log file {LOG_FILE}: {e}", file=sys.stderr)

# Обработчик для вывода в stderr (для OpenVPN и отладки)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.INFO)
stderr_handler.setFormatter(formatter)
logger.addHandler(stderr_handler)


# =============================================================================
# Функции скрипта
# =============================================================================

# Флаг для определения, используем ли мы тестовую БД (SQLite)
def _is_test_db():
    """Проверяет, используется ли тестовая БД (SQLite)."""
    return "sqlite" in str(engine.url).lower() or ":memory:" in str(engine.url).lower() or not os.getenv("DATABASE_URL")


def get_env_vars():
    """
    Получение переменных окружения от OpenVPN.

    Возвращает словарь с переменными:
    - common_name: CN сертификата клиента (обязательно)
    - bytes_sent: отправлено байт
    - bytes_received: получено байт
    - time_duration: длительность сессии в секундах

    Возвращает None, если отсутствует обязательная переменная common_name.
    """
    cn = os.environ.get('common_name')

    logger.debug("Environment variables: common_name=%s", cn)

    if not cn:
        logger.error(f"Missing required environment variable: common_name={cn}")
        return None

    # Парсим bytes_sent и bytes_received, по умолчанию 0
    try:
        bytes_sent = int(os.environ.get('bytes_sent', 0))
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid bytes_sent value, using 0: {e}")
        bytes_sent = 0

    try:
        bytes_received = int(os.environ.get('bytes_received', 0))
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid bytes_received value, using 0: {e}")
        bytes_received = 0

    env_vars = {
        'common_name': cn,
        'bytes_sent': bytes_sent,
        'bytes_received': bytes_received,
        'time_duration': os.environ.get('time_duration')
    }

    logger.info(
        f"Received disconnect from CN='{cn}', "
        f"bytes_sent={bytes_sent}, bytes_received={bytes_received}, "
        f"duration={env_vars['time_duration']}s"
    )
    return env_vars


def close_active_session(db, cn: str, bytes_sent: int, bytes_received: int,
                         server_id: int = None):
    """
    Закрывает последнюю активную сессию для указанного CN на ЭТОМ сервере.

    Находит последнюю активную сессию (ORDER BY connected_at DESC LIMIT 1)
    и обновляет её:
    - disconnected_at = NOW()
    - status = 'closed'
    - bytes_sent = переданное значение
    - bytes_received = переданное значение

    Мультисайт: скоуп по server_id — отключение на одном сайте не должно
    закрыть живую сессию того же CN на другом. Сессии с server_id IS NULL
    (legacy до мультисайта) считаются своими.

    Аргументы:
        db: сессия базы данных
        cn: Common Name из сертификата
        bytes_sent: количество отправленных байт
        bytes_received: количество полученных байт
        server_id: ID текущего сервера (None — без скоупа, старое поведение)

    Invariants: I5.1, I5.2, I5.3, I5.4, I5.6
    """
    logger.debug(f"Looking for active session for CN='{cn}'")

    # I5.1: Находим последнюю активную сессию по CN
    # ORDER BY connected_at DESC LIMIT 1 - берем только последнюю
    query = db.query(Session).join(Account).filter(
        Account.cn == cn,
        Session.status == 'active'
    )
    if server_id is not None:
        query = query.filter(
            or_(Session.server_id == server_id, Session.server_id.is_(None))
        )
    active_session = query.order_by(Session.connected_at.desc()).first()

    if active_session:
        logger.info(
            f"Found active session: id={active_session.id}, "
            f"account_id={active_session.account_id}, "
            f"connected_at={active_session.connected_at}"
        )

        # I5.2: Устанавливаем время отключения
        active_session.disconnected_at = utcnow()
        # I5.3: Меняем статус на 'closed'
        active_session.status = 'closed'
        # I5.4: Сохраняем статистику трафика
        active_session.bytes_sent = bytes_sent
        active_session.bytes_received = bytes_received
        # I5.6: Только UPDATE, никаких INSERT
        db.commit()

        duration = None
        if active_session.disconnected_at and active_session.connected_at:
            duration = (active_session.disconnected_at - active_session.connected_at).total_seconds()

        logger.info(
            f"Session closed: id={active_session.id}, "
            f"duration={duration}s, "
            f"bytes_sent={bytes_sent}, bytes_received={bytes_received}"
        )
    else:
        logger.warning(f"No active session found for CN='{cn}'")


def client_disconnect(db_session=None):
    """
    Главная функция скрипта client-disconnect.

    Обрабатывает отключение клиента и обновляет данные в БД.
    При любой ошибке возвращает 0, чтобы не блокировать VPN.

    Args:
        db_session: Опциональная сессия БД для тестирования.
                   Если не передана, создается новая сессия через SessionLocal.

    Возвращает:
        int: код выхода (всегда 0)

    Invariants: I5.1, I5.2, I5.3, I5.4, I5.5, I5.6
    """
    logger.info("=" * 60)
    logger.info("Starting client-disconnect script")

    # I5.5: если импорт core.* не удался — не блокируем VPN
    if _IMPORT_ERROR is not None:
        logger.error(
            "client-disconnect: ошибка импорта зависимостей, VPN не блокируется: %s",
            _IMPORT_ERROR,
        )
        return 0

    # I5.1: Читаем переменные окружения
    env_vars = get_env_vars()
    if env_vars is None:
        # I5.5: Не блокируем VPN при отсутствии переменных
        logger.error("Failed to get environment variables, exiting with 0")
        return 0

    db = db_session
    should_close = False
    try:
        # Подключаемся к БД, если сессия не передана извне
        if db is None:
            logger.debug("Creating new database session")
            db = SessionLocal()
            should_close = True
        else:
            logger.debug("Using provided database session")

        # Мультисайт: находим ЭТОТ инстанс (create=False — I5.6, disconnect
        # ничего не создаёт; connect уже зарегистрировал сервер). Если записи
        # нет (сюда не подключались) — работаем без скоупа, как раньше.
        server_id = None
        try:
            server_id = resolve_server_id(db, SERVER_NAME, create=False)
        except Exception as server_exc:  # noqa: BLE001
            logger.error(
                "Не удалось определить сервер '%s', закрытие без скоупа: %s",
                SERVER_NAME, server_exc,
            )

        # I5.1, I5.2, I5.3, I5.4, I5.6: Закрываем активную сессию
        close_active_session(
            db,
            env_vars['common_name'],
            env_vars['bytes_sent'],
            env_vars['bytes_received'],
            server_id
        )

        logger.info("Client-disconnect completed successfully")
        return 0

    except Exception as e:
        # I5.5: При любой ошибке возвращаем 0, не блокируем VPN
        logger.exception(f"Error in client_disconnect: {e}")
        return 0
    finally:
        if should_close and db:
            try:
                db.close()
                logger.debug("Database session closed")
            except Exception as e:
                logger.error(f"Error closing database session: {e}")


def main():
    """
    Точка входа для скрипта client-disconnect.

    ВАЖНО: Всегда возвращает 0, чтобы не блокировать отключение от VPN
    при любых ошибках. OpenVPN ожидает exit 0 для успешного выполнения
    скрипта client-disconnect.
    """
    try:
        exit_code = client_disconnect()
        # Гарантируем, что exit_code всегда 0
        return 0 if exit_code != 0 else exit_code
    except Exception as e:
        # Логируем ошибку но НЕ блокируем VPN
        logger.exception(f"client-disconnect fatal error: {e}")
        return 0  # Всегда возвращаем 0 для OpenVPN


if __name__ == '__main__':
    sys.exit(main())
