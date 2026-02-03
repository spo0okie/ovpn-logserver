#!/usr/bin/env python3
"""
Скрипт для обнаружения и очистки orphaned-сессий OpenVPN.

Сравнивает активные сессии в БД со списком клиентов из Management Interface.
Сессии, CN которых отсутствуют в Management Interface, помечаются как 'error'.

Инварианты:
- C1.1: Находит все сессии status='active'
- C1.2: Для каждой активной сессии проверяет наличие CN в Management Interface
- C1.3: Сессия помечается как status='error' если CN отсутствует в mgmt
- C1.4: Устанавливает disconnected_at = NOW() для orphaned сессий
- C1.5: Логирует каждую orphaned сессию с CN и session_id
- C1.6: Функция cleanup_orphaned_sessions() идемпотентна
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Set, List, Tuple

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import event
from sqlalchemy.engine import Engine

from core.database import SessionLocal, engine
from core.models import Session, Account

# ============================================================================
# Настройка логирования
# ============================================================================

# Создаем директорию для логов если её нет
LOG_DIR = Path("/var/log/openvpn-logserver")
if not LOG_DIR.exists():
    # Fallback для тестов - используем текущую директорию
    LOG_DIR = Path(__file__).parent.parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "session-cleanup.log"

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Форматтер для логов
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Обработчик для записи в файл
try:
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except (PermissionError, OSError) as e:
    print(f"Warning: Cannot write to log file {LOG_FILE}: {e}", file=sys.stderr)

# Обработчик для вывода в stderr
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.INFO)
stderr_handler.setFormatter(formatter)
logger.addHandler(stderr_handler)


# ============================================================================
# Функции скрипта
# ============================================================================

def get_active_sessions(db) -> List[Session]:
    """
    Возвращает все сессии со статусом 'active'.

    Invariant C1.1: Находит все сессии status='active'

    Args:
        db: сессия базы данных

    Returns:
        List[Session]: Список активных сессий
    """
    return db.query(Session).filter(Session.status == 'active').all()


def get_orphaned_sessions(active_sessions: List[Session], connected_cns: Set[str]) -> List[Session]:
    """
    Определяет orphaned сессии - те, CN которых нет в Management Interface.

    Invariant C1.2: Для каждой активной сессии проверяет наличие CN в mgmt

    Args:
        active_sessions: Список активных сессий
        connected_cns: Множество CN клиентов из Management Interface

    Returns:
        List[Session]: Список orphaned сессий
    """
    orphaned = []
    for session in active_sessions:
        # Получаем CN из связанного аккаунта
        if session.account and session.account.cn:
            cn = session.account.cn
            # C1.2: Проверяем наличие CN в Management Interface
            if cn not in connected_cns:
                orphaned.append(session)
        else:
            # Если аккаунт не найден, сессия считается orphaned
            logger.warning(
                f"Session {session.id} has no associated account, "
                f"marking as orphaned"
            )
            orphaned.append(session)

    return orphaned


def mark_session_as_orphaned(db, session: Session) -> None:
    """
    Помечает сессию как orphaned: устанавливает status='error' и disconnected_at.

    Invariant C1.3: Сессия помечается как status='error' если CN отсутствует
    Invariant C1.4: Устанавливает disconnected_at = NOW()

    Args:
        db: сессия базы данных
        session: Сессия для пометки
    """
    cn = session.account.cn if session.account else "unknown"

    # C1.3: Устанавливаем статус 'error'
    session.status = 'error'

    # C1.4: Устанавливаем время отключения
    session.disconnected_at = datetime.utcnow()

    db.commit()

    # C1.5: Логируем orphaned сессию
    logger.info(
        f"Orphaned session marked as error: "
        f"session_id={session.id}, cn='{cn}', "
        f"connected_at={session.connected_at}, "
        f"disconnected_at={session.disconnected_at}"
    )


def cleanup_orphaned_sessions(db, connected_cns: Set[str] = None) -> Tuple[int, int]:
    """
    Выполняет очистку orphaned сессий.

    Сравнивает активные сессии в БД со списком клиентов из Management Interface.
    Сессии, CN которых отсутствуют в Management Interface, помечаются как 'error'.

    Invariant C1.6: Функция идемпотентна (повторный запуск не меняет уже закрытые сессии)

    Args:
        db: сессия базы данных
        connected_cns: Опционально - множество CN из Management Interface.
                      Если None, запрашивает через mgmt_client.

    Returns:
        Tuple[int, int]: (количество найденных orphaned сессий, количество помеченных)
    """
    logger.info("Starting orphaned session cleanup")

    # C1.1: Получаем все активные сессии
    active_sessions = get_active_sessions(db)
    active_count = len(active_sessions)
    logger.info(f"Found {active_count} active sessions")

    # Если нет активных сессий, ничего не делаем
    if active_count == 0:
        logger.info("No active sessions to process")
        return 0, 0

    # Получаем список CN из Management Interface если не передан
    if connected_cns is None:
        try:
            from collector.mgmt_client import get_connected_clients
            connected_cns = get_connected_clients()
        except Exception as e:
            logger.error(f"Failed to get connected clients from mgmt: {e}")
            connected_cns = set()

    logger.info(f"Found {len(connected_cns)} connected clients in mgmt interface")

    # C1.2: Определяем orphaned сессии
    orphaned_sessions = get_orphaned_sessions(active_sessions, connected_cns)
    orphaned_count = len(orphaned_sessions)

    logger.info(f"Found {orphaned_count} orphaned sessions")

    # C1.3-C1.5: Помечаем orphaned сессии
    marked_count = 0
    for session in orphaned_sessions:
        # C1.6: Идемпотентность - пропускаем если уже помечен как error
        if session.status == 'error':
            logger.debug(
                f"Session {session.id} already marked as error, skipping"
            )
            continue

        mark_session_as_orphaned(db, session)
        marked_count += 1

    logger.info(
        f"Orphaned session cleanup completed: "
        f"active={active_count}, orphaned={orphaned_count}, marked={marked_count}"
    )

    return orphaned_count, marked_count


def main():
    """
    Главная функция скрипта.
    """
    logger.info("=" * 60)
    logger.info("Starting session-cleanup script")

    db = None
    try:
        # Создаем сессию БД
        db = SessionLocal()

        # Выполняем очистку
        orphaned_count, marked_count = cleanup_orphaned_sessions(db)

        logger.info(f"Cleanup completed: {orphaned_count} orphaned, {marked_count} marked")
        return 0

    except Exception as e:
        logger.exception(f"Error in session cleanup: {e}")
        return 1
    finally:
        if db:
            try:
                db.close()
            except Exception as e:
                logger.error(f"Error closing database session: {e}")


if __name__ == '__main__':
    sys.exit(main())
