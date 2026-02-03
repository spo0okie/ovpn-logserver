"""
Скрипт проверки CCD (Client Config Directory) файлов.

Обновляет has_ccd и ccd_updated_at в БД на основе наличия CCD файлов.

Инварианты:
- I6.3: Обновляет has_ccd, ccd_updated_at
- I6.4: Идемпотентен (повторный запуск не ломает данные)
- I6.5: Только UPDATE операции, никаких INSERT для accounts
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import Account
from collector.config import CCD_DIR

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

def find_ccd_files(ccd_dir: str) -> dict:
    """
    Находит все CCD файлы в директории.

    Args:
        ccd_dir: Путь к директории с CCD файлами

    Returns:
        dict: Словарь {filename: modification_time} для всех CCD файлов
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
            # Имя файла без расширения считаем CN клиента
            cn = file_path.stem
            # Получаем время модификации файла
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            ccd_files[cn] = mtime
            file_count += 1

    logger.debug(f"Found {file_count} CCD files in {ccd_dir}")
    return ccd_files


def check_ccd(db=None, ccd_dir: str = None) -> dict:
    """
    Проверяет наличие CCD файлов и обновляет статус в БД.

    Находит все файлы в CCD_DIR, обновляет has_ccd=True, ccd_updated_at=NOW()
    для найденных. Обновляет has_ccd=False для не найденных.

    Args:
        db: Сессия базы данных (если None, создается новая)
        ccd_dir: Директория с CCD файлами (если None, используется CCD_DIR)

    Returns:
        dict: Статистика проверки:
            - checked: количество проверенных записей
            - with_ccd: количество записей с CCD
            - without_ccd: количество записей без CCD
            - errors: количество ошибок

    Invariants: I6.3, I6.4, I6.5
    """
    stats = {
        'checked': 0,
        'with_ccd': 0,
        'without_ccd': 0,
        'errors': 0,
    }

    # Используем переданную директорию или дефолтную
    target_ccd_dir = ccd_dir or CCD_DIR

    logger.info("=" * 60)
    logger.info("Starting CCD check")
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
        # Получаем все accounts
        accounts = db.query(Account).all()
        logger.info(f"Checking {len(accounts)} accounts for CCD files")

        for account in accounts:
            stats['checked'] += 1

            # I6.3: Проверяем наличие CCD файла
            if account.cn in ccd_files:
                # I6.3: CCD файл найден
                # I6.4: Идемпотентность - обновляем только если изменилось
                file_mtime = ccd_files[account.cn]

                if not account.has_ccd or account.ccd_updated_at != file_mtime:
                    account.has_ccd = True
                    account.ccd_updated_at = file_mtime
                    logger.debug(f"Updated CCD status for CN='{account.cn}': has_ccd=True, mtime={file_mtime}")

                stats['with_ccd'] += 1
            else:
                # I6.3: CCD файл не найден
                # I6.4: Идемпотентность - сбрасываем статус
                if account.has_ccd:
                    account.has_ccd = False
                    account.ccd_updated_at = None
                    logger.debug(f"Updated CCD status for CN='{account.cn}': has_ccd=False")

                stats['without_ccd'] += 1

        # Сохраняем изменения
        db.commit()
        logger.info(
            f"CCD check completed: "
            f"checked={stats['checked']}, "
            f"with_ccd={stats['with_ccd']}, "
            f"without_ccd={stats['without_ccd']}, "
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
