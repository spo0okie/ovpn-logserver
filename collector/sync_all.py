"""
Модуль для периодической синхронизации данных.

Выполняет фоновые задачи:
- Синхронизация сертификатов (cert_sync) — создание accounts из неотозванных сертификатов
- Проверка CRL (crl_checker) — обновление статуса отзыва
- Проверка CCD файлов (ccd_checker) — обновление has_ccd
- Очистка orphaned сессий (session_cleanup) — помечает "зависшие" сессии как error

Запускается через systemd timer (openvpn-sync.timer).

Порядок выполнения важен:
1. cert_sync создаёт accounts для неотозванных CN из сертификатов
2. crl_checker обновляет is_revoked для всех accounts
3. ccd_checker обновляет has_ccd для всех accounts
4. session_cleanup помечает orphaned сессии (ПОСЛЕ успешного выполнения предыдущих)
"""

import sys
import os
import logging

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from collector.cert_sync import sync_certificates
from collector.crl_checker import check_crl
from collector.ccd_checker import check_ccd
from collector.session_cleanup import cleanup_orphaned_sessions

# Настройка логирования
logger = logging.getLogger(__name__)


def run_sync():
    """
    Запускает все задачи синхронизации.

    Выполняет последовательно:
    1. Синхронизацию сертификатов (создание accounts из неотозванных)
    2. Проверку CRL (обновление is_revoked)
    3. Проверку CCD файлов (обновление has_ccd)
    4. Очистку orphaned сессий (ПОСЛЕ успешного выполнения предыдущих)

    Invariant S3.1: session_cleanup вызывается ПОСЛЕ успешного выполнения всех остальных sync-задач
    Invariant S3.2: session_cleanup вызывается ТОЛЬКО если предыдущие задачи завершились успешно
    Invariant S3.3: При ошибке session_cleanup - логируется, но не блокирует следующие запуски

    Порядок важен: cert_sync должен выполняться первым для создания
    accounts, затем crl_checker и ccd_checker обновляют доп. поля,
    и только потом session_cleanup помечает orphaned сессии.

    Returns:
        int: 0 при успехе, 1 при ошибке
    """
    db = None
    try:
        db = SessionLocal()

        # Суммарные "мягкие" ошибки шагов (шаг вернул stats['errors']>0, но не
        # бросил исключение). Жёсткое исключение любого шага пробрасывается в
        # outer except → fail-fast, cleanup не выполняется, exit 1.
        sync_errors = 0

        # 1. cert_sync — создаёт accounts, обновляет valid_from/valid_to
        print("Starting certificate sync...")
        cert_stats = sync_certificates(db) or {}
        print(f"Certificate sync completed: {cert_stats}")
        sync_errors += cert_stats.get("errors", 0)

        # 2. crl_checker — обновляет is_revoked/revoked_at
        print("Starting CRL check...")
        crl_stats = check_crl(db) or {}
        print(f"CRL check completed: {crl_stats}")
        sync_errors += crl_stats.get("errors", 0)

        # 3. ccd_checker — обновляет has_ccd/ccd_updated_at
        print("Starting CCD check...")
        ccd_stats = check_ccd(db) or {}
        print(f"CCD check completed: {ccd_stats}")
        sync_errors += ccd_stats.get("errors", 0)

        # S3.1/S3.2: session_cleanup выполняется ТОЛЬКО если предыдущие шаги
        # прошли без ошибок. Иначе состояние accounts/сессий может быть неполным
        # и cleanup ошибочно пометит живые сессии как orphaned.
        if sync_errors == 0:
            try:
                print("Starting session cleanup...")
                orphaned_count, marked_count = cleanup_orphaned_sessions(db)
                print(f"Session cleanup completed: {orphaned_count} orphaned, {marked_count} marked")
            except Exception as e:
                # S3.3: ошибка cleanup логируется, но не блокирует (exit не 1)
                print(f"Session cleanup error (non-blocking): {e}", file=sys.stderr)
                logger.error(f"Session cleanup failed: {e}")
        else:
            print(
                f"Skipping session cleanup: предыдущие шаги дали {sync_errors} ошибок "
                f"(S3.2 — cleanup только после успешного синка)",
                file=sys.stderr,
            )
            logger.warning(
                "session_cleanup пропущен из-за %d ошибок в предыдущих шагах", sync_errors
            )

        # exit != 0 при ошибках синка — иначе systemd не увидит сбой
        return 0 if sync_errors == 0 else 1

    except Exception as e:
        print(f"Error during sync: {e}", file=sys.stderr)
        return 1

    finally:
        if db:
            try:
                db.close()
            except Exception as e:
                print(f"Error closing database session: {e}", file=sys.stderr)


def main():
    """Точка входа для запуска синхронизации."""
    exit_code = run_sync()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
