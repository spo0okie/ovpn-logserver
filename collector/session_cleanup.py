#!/usr/bin/env python3
"""
Скрипт для обнаружения и очистки orphaned-сессий OpenVPN.

Сравнивает активные сессии в БД со списком клиентов из Management Interface.
Сессии, CN которых отсутствуют в Management Interface, помечаются status='error'.

Корректность под race с client-connect обеспечивается snapshot_time: помечаются
только те сессии, которые существовали ДО снятия снимка mgmt — свежесозданные
сессии (например, при reconnect) не трогаются.

Мультисайт: management-сокет локален для ЭТОГО инстанса OpenVPN, поэтому
сравнивать с ним можно ТОЛЬКО сессии этого сервера (sessions.server_id).
Без скоупа первый же запуск на любом сайте пометил бы error все живые сессии
остальных сайтов. Сессии с server_id IS NULL (legacy до мультисайта)
считаются своими — они созданы единственным существовавшим тогда сервером.

Инварианты:
- C1.1: Находит все сессии status='active' (с connected_at < snapshot_time).
- C1.2: Для каждой активной сессии проверяет наличие CN в Management Interface.
- C1.3: Сессия помечается как status='error' если CN отсутствует в mgmt.
- C1.4: Устанавливает disconnected_at = snapshot_time для orphaned сессий.
- C1.5: Логирует каждую orphaned сессию с CN и session_id.
- C1.6: Функция cleanup_orphaned_sessions() идемпотентна.
- C1.7: Fail-closed при недоступном mgmt и при пустом ответе mgmt с
        непустым списком active.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.time import utcnow

from sqlalchemy import or_  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from core.models import Session  # noqa: E402
from collector.config import SERVER_NAME  # noqa: E402
from collector.server_registry import resolve_server_id  # noqa: E402

# ============================================================================
# Логирование
# ============================================================================

LOG_DIR = Path("/var/log/openvpn-logserver")
if not LOG_DIR.exists():
    LOG_DIR = Path(__file__).parent.parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "session-cleanup.log"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

try:
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except (PermissionError, OSError) as exc:
    print(f"Warning: cannot write to log file {LOG_FILE}: {exc}", file=sys.stderr)

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.INFO)
stderr_handler.setFormatter(formatter)
logger.addHandler(stderr_handler)


# ============================================================================
# Логика
# ============================================================================


def get_active_sessions(
    db, before: Optional[datetime] = None, server_id: Optional[int] = None
) -> List[Session]:
    """
    Возвращает все сессии status='active'.
    Если задан `before` — только те, что существовали до этого момента (C1.1).
    Если задан `server_id` — только сессии этого сервера и legacy-строки с
    server_id IS NULL (мультисайт: чужие сайты не трогаем).
    """
    query = db.query(Session).filter(Session.status == "active")
    if before is not None:
        query = query.filter(Session.connected_at < before)
    if server_id is not None:
        query = query.filter(
            or_(Session.server_id == server_id, Session.server_id.is_(None))
        )
    return query.all()


def get_orphaned_sessions(
    active_sessions: List[Session], connected_cns: Set[str]
) -> List[Session]:
    """Сессии без CN в connected_cns (C1.2)."""
    orphaned = []
    for session in active_sessions:
        if session.account and session.account.cn:
            if session.account.cn not in connected_cns:
                orphaned.append(session)
        else:
            logger.warning(
                "Session %s has no associated account, marking as orphaned",
                session.id,
            )
            orphaned.append(session)
    return orphaned


def cleanup_orphaned_sessions(
    db, connected_cns: Optional[Set[str]] = None,
    server_id: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Помечает orphaned active-сессии ЭТОГО сервера как error.

    Мультисайт: сравнение с mgmt валидно только в пределах одного инстанса,
    поэтому cleanup работает строго по server_id. Если server_id не передан,
    инстанс определяется по имени из конфигурации (openvpn.server_name);
    ошибка определения — fail-closed, cleanup пропускается (в духе C1.7).
    Legacy-сессии с server_id IS NULL считаются своими.

    Возвращает (orphaned_count, marked_count).
    Идемпотентна (C1.6): повторный запуск не меняет уже закрытые сессии.
    """
    logger.info("Starting orphaned session cleanup (server '%s')", SERVER_NAME)

    snapshot_time = utcnow()

    if server_id is None:
        try:
            server_id = resolve_server_id(db, SERVER_NAME)
        except Exception as exc:
            logger.error(
                "Failed to resolve server '%s': %s — skipping cleanup",
                SERVER_NAME, exc,
            )
            return 0, 0

    if connected_cns is None:
        try:
            from collector.mgmt_client import get_connected_clients
            connected_cns = get_connected_clients()
        except Exception as exc:
            logger.error("Failed to query mgmt: %s — skipping cleanup", exc)
            return 0, 0

    # C1.1: активные сессии до snapshot_time, чтобы не зацепить свежий reconnect.
    # Только сессии ЭТОГО сервера (+ legacy NULL).
    active_sessions = get_active_sessions(db, before=snapshot_time, server_id=server_id)
    active_count = len(active_sessions)
    logger.info(
        "Active sessions before snapshot: %d, mgmt connected: %d",
        active_count,
        len(connected_cns),
    )

    if active_count == 0:
        return 0, 0

    # C1.7: fail-closed — если mgmt вернул 0 клиентов при непустом active,
    # высока вероятность, что сокет временно перезапущен/недоступен; не
    # трогаем сессии, чтобы не выставить error пачкой.
    if len(connected_cns) == 0:
        logger.warning(
            "MGMT returned 0 clients while %d active sessions exist — skipping cleanup",
            active_count,
        )
        return 0, 0

    orphaned_sessions = get_orphaned_sessions(active_sessions, connected_cns)
    orphaned_count = len(orphaned_sessions)

    marked_count = 0
    for session in orphaned_sessions:
        if session.status == "error":
            continue
        cn = session.account.cn if session.account else "unknown"
        session.status = "error"
        session.disconnected_at = snapshot_time
        marked_count += 1
        logger.info(
            "Orphaned session marked as error: id=%s, cn=%s, connected_at=%s",
            session.id,
            cn,
            session.connected_at,
        )

    if marked_count:
        db.commit()

    logger.info(
        "Cleanup done: active=%d orphaned=%d marked=%d",
        active_count,
        orphaned_count,
        marked_count,
    )
    return orphaned_count, marked_count


# Сохраняем для совместимости со старыми вызовами.
def mark_session_as_orphaned(db, session: Session) -> None:
    """Помечает одну сессию как orphaned и коммитит. Используется в тестах."""
    cn = session.account.cn if session.account else "unknown"
    session.status = "error"
    session.disconnected_at = utcnow()
    db.commit()
    logger.info(
        "Orphaned session marked as error: id=%s, cn=%s, disconnected_at=%s",
        session.id,
        cn,
        session.disconnected_at,
    )


def main():
    logger.info("=" * 60)
    logger.info("Starting session-cleanup script")
    db = None
    try:
        db = SessionLocal()
        orphaned_count, marked_count = cleanup_orphaned_sessions(db)
        logger.info("Cleanup completed: %d orphaned, %d marked", orphaned_count, marked_count)
        return 0
    except Exception as exc:
        logger.exception("Error in session cleanup: %s", exc)
        return 1
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logger.error("Error closing DB session: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
