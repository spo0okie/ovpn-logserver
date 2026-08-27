"""
Скрипт проверки CCD (Client Config Directory) файлов.

Мультисайт: CCD-файлы лежат на КАЖДОМ сервере отдельно, поэтому checker
запускается на каждом инстансе и ведёт per-site наличие в таблице ccd_status
(строка = (cn, server) — CCD есть). Поверх этого пересчитывается агрегат в
accounts: has_ccd = «CCD есть хотя бы на одном сервере».

Файлы `<cn>_OFF` (usr.push при disable делает mv в `<cn>_OFF`) — архив
выключенного доступа, который админы оставляют для справки; для мониторинга
это отсутствие CCD, такие файлы игнорируются.

Инварианты:
- I6.3: Обновляет has_ccd, ccd_updated_at
- I6.4: Идемпотентен (повторный запуск не ломает данные)
- I6.5: Только UPDATE операции, никаких INSERT для accounts
  (INSERT в ccd_status/vpn_servers — это НЕ accounts, инвариант сохраняется)
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.time import utcfromtimestamp

from core.database import SessionLocal
from core.models import Account, CcdStatus
from collector.config import CCD_DIR, SERVER_NAME
from collector.server_registry import resolve_server_id

# =============================================================================
# Настройка логирования
# =============================================================================

# Создаем директорию для логов если её нет
LOG_DIR = Path("/var/log/openvpn-logserver")
if not LOG_DIR.exists():
    # Fallback для тестов - используем текущую директорию
    LOG_DIR = Path(__file__).parent.parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "ccd-checker.log"

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

# Обработчик для вывода в stderr (для отладки)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.INFO)
stderr_handler.setFormatter(formatter)
logger.addHandler(stderr_handler)


# =============================================================================
# Функции скрипта
# =============================================================================

# Суффикс выключенного CCD (provision/multisite: usr.push делает mv в <cn>_OFF).
# Такие файлы — архив для админов, для мониторинга это отсутствие CCD.
CCD_OFF_SUFFIX = "_OFF"


def find_ccd_files(ccd_dir: str) -> dict:
    """
    Находит все CCD файлы в директории.

    Файлы `<cn>_OFF` (выключенный доступ, архив) игнорируются.

    Args:
        ccd_dir: Путь к директории с CCD файлами

    Returns:
        dict: Словарь {cn: modification_time} для всех CCD файлов
    """
    ccd_path = Path(ccd_dir)
    if not ccd_path.exists() or not ccd_path.is_dir():
        logger.warning(f"CCD directory not found: {ccd_dir}")
        return {}

    ccd_files = {}

    # Ищем все файлы в директории CCD
    file_count = 0
    for file_path in ccd_path.iterdir():
        if file_path.is_file():
            # CCD-файл именуется РОВНО по CN (без расширения). Используем полное
            # имя файла, а не .stem — иначе CN с точкой (john.doe) обрежется до
            # "john" и статус has_ccd попадёт не тому аккаунту.
            cn = file_path.name
            # Пропускаем скрытые и редакторские backup-файлы (.swp, name~)
            if cn.startswith(".") or cn.endswith("~"):
                continue
            # <cn>_OFF — выключенный доступ: CCD считается отсутствующим
            if cn.endswith(CCD_OFF_SUFFIX):
                logger.debug(f"Skipping disabled CCD file: {cn}")
                continue
            # mtime в naive-UTC — единый стиль времени в проекте (не локальное!)
            mtime = utcfromtimestamp(file_path.stat().st_mtime)
            ccd_files[cn] = mtime
            file_count += 1

    logger.debug(f"Found {file_count} CCD files in {ccd_dir}")
    return ccd_files


def sync_ccd_status(db, server_id: int, ccd_files: dict) -> dict:
    """
    Приводит строки ccd_status ЭТОГО сервера в соответствие с файлами на диске.

    Найденный файл — upsert строки (ccd_updated_at по mtime); строка без файла —
    удаляется (отсутствие файла = отсутствие строки). Строки других серверов
    не трогаются.

    Returns:
        dict: {"found": N, "removed": N}
    """
    counters = {"found": 0, "removed": 0}

    existing = {
        row.cn: row
        for row in db.query(CcdStatus).filter(CcdStatus.server_id == server_id).all()
    }

    for cn, mtime in ccd_files.items():
        row = existing.pop(cn, None)
        if row is None:
            db.add(CcdStatus(
                cn=cn,
                server_id=server_id,
                ccd_updated_at=mtime,
            ))
        # I6.4: идемпотентность — пишем только при изменении
        elif row.ccd_updated_at != mtime:
            row.ccd_updated_at = mtime
        counters["found"] += 1

    for row in existing.values():
        logger.debug(f"CCD file gone for CN='{row.cn}' on server {server_id}, removing status")
        db.delete(row)
        counters["removed"] += 1

    return counters


def update_accounts_ccd_aggregate(db, stats: dict) -> None:
    """
    Пересчитывает агрегат в accounts из ccd_status ПО ВСЕМ серверам.

    has_ccd = «CCD есть хотя бы на одном сервере»,
    ccd_updated_at = максимальный mtime среди серверов.

    Пересчёт из таблицы (а не из локальных файлов) делает конкурентные запуски
    checker'ов разных сайтов безопасными: каждый обновляет только свои строки
    ccd_status, агрегат у обоих сходится к одному значению.

    Invariants: I6.3, I6.4, I6.5 (для accounts — только UPDATE)
    """
    enabled = {}
    for row in db.query(CcdStatus).all():
        current = enabled.get(row.cn)
        if current is None or (row.ccd_updated_at and row.ccd_updated_at > current):
            enabled[row.cn] = row.ccd_updated_at

    accounts = db.query(Account).all()
    logger.info(f"Updating CCD aggregate for {len(accounts)} accounts")

    for account in accounts:
        stats['checked'] += 1

        if account.cn in enabled:
            # I6.4: Идемпотентность - обновляем только если изменилось
            file_mtime = enabled[account.cn]
            if not account.has_ccd or account.ccd_updated_at != file_mtime:
                account.has_ccd = True
                account.ccd_updated_at = file_mtime
                logger.debug(f"Updated CCD status for CN='{account.cn}': has_ccd=True, mtime={file_mtime}")
            stats['with_ccd'] += 1
        else:
            # I6.4: Идемпотентность - сбрасываем статус
            if account.has_ccd:
                account.has_ccd = False
                account.ccd_updated_at = None
                logger.debug(f"Updated CCD status for CN='{account.cn}': has_ccd=False")
            stats['without_ccd'] += 1


def check_ccd(db=None, ccd_dir: str = None, server_id: int = None) -> dict:
    """
    Проверяет CCD файлы и обновляет статус в БД.

    Два шага в одной транзакции:
    1. per-site: строки ccd_status ЭТОГО сервера приводятся к файлам на диске
       (есть файл `<cn>` — есть строка; `<cn>_OFF` и отсутствие файла — строки нет);
    2. агрегат: accounts.has_ccd/ccd_updated_at пересчитываются из ccd_status
       по всем серверам («есть хотя бы где-то»).

    Args:
        db: Сессия базы данных (если None, создается новая)
        ccd_dir: Директория с CCD файлами (если None, используется CCD_DIR)
        server_id: ID сервера (если None, определяется по openvpn.server_name)

    Returns:
        dict: Статистика проверки:
            - checked: количество проверенных accounts
            - with_ccd: accounts с CCD (агрегат)
            - without_ccd: accounts без CCD
            - site_found/site_removed: per-site изменения этого сервера
            - errors: количество ошибок

    Invariants: I6.3, I6.4, I6.5
    """
    stats = {
        'checked': 0,
        'with_ccd': 0,
        'without_ccd': 0,
        'site_found': 0,
        'site_removed': 0,
        'errors': 0,
    }

    # Используем переданную директорию или дефолтную
    target_ccd_dir = ccd_dir or CCD_DIR

    logger.info("=" * 60)
    logger.info(f"Starting CCD check (server '{SERVER_NAME}')")
    logger.info(f"CCD directory: {target_ccd_dir}")

    # Находим все CCD файлы
    ccd_files = find_ccd_files(target_ccd_dir)
    logger.info(f"Found {len(ccd_files)} CCD files")

    # Создаем сессию БД если не передана
    close_db = False
    if db is None:
        logger.debug("Creating new database session")
        db = SessionLocal()
        close_db = True
    else:
        logger.debug("Using provided database session")

    try:
        if server_id is None:
            server_id = resolve_server_id(db, SERVER_NAME)

        counters = sync_ccd_status(db, server_id, ccd_files)
        stats['site_found'] = counters['found']
        stats['site_removed'] = counters['removed']

        # flush, чтобы агрегат ниже видел свежие строки ccd_status
        db.flush()
        update_accounts_ccd_aggregate(db, stats)

        # Сохраняем изменения
        db.commit()
        logger.info(
            f"CCD check completed: "
            f"checked={stats['checked']}, "
            f"with_ccd={stats['with_ccd']}, "
            f"without_ccd={stats['without_ccd']}, "
            f"site_found={stats['site_found']}, "
            f"site_removed={stats['site_removed']}, "
            f"errors={stats['errors']}"
        )

    except Exception as e:
        db.rollback()
        logger.exception(f"Error during CCD check: {e}")
        stats['errors'] += 1
    finally:
        if close_db:
            db.close()
            logger.debug("Database session closed")

    return stats


def main():
    """Точка входа для скрипта."""
    stats = check_ccd()
    print(f"CCD check completed: {stats}")
    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
