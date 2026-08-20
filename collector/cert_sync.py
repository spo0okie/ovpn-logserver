"""
Скрипт синхронизации сертификатов.

Сканирует директорию с сертификатами и синхронизирует данные с БД:
1. Создает accounts для всех неотозванных сертификатов (новое поведение)
2. Обновляет valid_from и valid_to для всех найденных сертификатов
3. Помечает отозванные сертификаты как is_revoked=True

Инварианты:
- I6.1: Обновляет valid_from, valid_to из сертификатов
- I6.4: Идемпотентен (повторный запуск не ломает данные)
- I6.5: INSERT или UPDATE — создает новые accounts для неотозванных CN
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.database import SessionLocal
from core.models import Account
from core.serial import normalize_serial
from collector.config import CERTS_DIR, CERT_EXTENSION, CRL_FILE

# =============================================================================
# Настройка логирования
# =============================================================================

# Создаем директорию для логов если её нет
LOG_DIR = Path("/var/log/openvpn-logserver")
if not LOG_DIR.exists():
    # Fallback для тестов - используем текущую директорию
    LOG_DIR = Path(__file__).parent.parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "cert-sync.log"

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

def extract_cert_info(cert_path: str) -> dict:
    """
    Извлекает информацию из сертификата.

    Args:
        cert_path: Путь к файлу сертификата в формате PEM

    Returns:
        dict: Словарь с полями:
            - cn: Common Name из сертификата
            - serial_number: серийный номер сертификата
            - valid_from: datetime начала действия
            - valid_to: datetime окончания действия
            - None если не удалось распарсить
    """
    try:
        logger.debug(f"Parsing certificate: {cert_path}")

        with open(cert_path, 'rb') as f:
            cert_data = f.read()

        # Парсим сертификат
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())

        # Извлекаем CN из Subject
        cn = None
        for attr in cert.subject:
            if attr.oid == NameOID.COMMON_NAME:
                cn = attr.value
                break

        if not cn:
            logger.warning(f"Certificate {cert_path} has no CN")
            return None

        # Получаем даты валидности (приводим к naive-UTC, т.к. в БД naive)
        valid_from = cert.not_valid_before_utc.replace(tzinfo=None)
        valid_to = cert.not_valid_after_utc.replace(tzinfo=None)
        serial_number = normalize_serial(cert.serial_number)

        logger.debug(
            f"Certificate parsed: cn='{cn}', serial='{serial_number}', "
            f"valid_from={valid_from}, valid_to={valid_to}"
        )

        return {
            'cn': cn,
            'serial_number': serial_number,
            'valid_from': valid_from,
            'valid_to': valid_to,
        }
    except Exception as e:
        logger.error(f"Error parsing certificate {cert_path}: {e}")
        return None


def parse_crl(crl_path: str) -> set:
    """
    Парсит CRL файл и возвращает множество отозванных серийных номеров.

    Args:
        crl_path: Путь к CRL файлу в формате PEM

    Returns:
        set: Множество отозванных серийных номеров (строки)
             Пустое множество если CRL не найден или ошибка парсинга
    """
    try:
        if not Path(crl_path).exists():
            # CRL файл может отсутствовать — это нормально
            logger.info(f"CRL file not found: {crl_path}, assuming empty")
            return set()

        logger.debug(f"Parsing CRL file: {crl_path}")

        with open(crl_path, 'rb') as f:
            crl_data = f.read()

        # Парсим CRL
        crl = x509.load_pem_x509_crl(crl_data, default_backend())

        # Собираем серийные номера отозванных сертификатов (нормализованный hex)
        revoked_serials = set()
        for revoked_cert in crl:
            revoked_serials.add(normalize_serial(revoked_cert.serial_number))

        logger.info(f"CRL parsed: {len(revoked_serials)} revoked certificates found")
        logger.debug(f"Revoked serials: {revoked_serials}")

        return revoked_serials
    except Exception as e:
        logger.error(f"Error parsing CRL {crl_path}: {e}")
        return set()


def find_cert_files(certs_dir: str) -> list:
    """
    Находит все файлы сертификатов в директории.

    Args:
        certs_dir: Путь к директории с сертификатами

    Returns:
        list: Список путей к файлам сертификатов
    """
    certs_path = Path(certs_dir)
    if not certs_path.exists() or not certs_path.is_dir():
        logger.warning(f"Certificates directory not found: {certs_dir}")
        return []

    # Ищем файлы с расширением .crt (или другим указанным)
    cert_files = list(certs_path.glob(f"*{CERT_EXTENSION}"))
    logger.debug(f"Found {len(cert_files)} certificate files in {certs_dir}")

    if not cert_files:
        # Каталог есть, но подходящих файлов нет. Чаще всего это опечатка в
        # путях/расширении: синк молча превращается в no-op, даты сертификатов
        # никогда не заполняются, и заметить это можно только по пустым
        # valid_to в БД. Поэтому логируем громко и показываем, что реально
        # лежит в каталоге.
        present = sorted({
            (f.suffix or "<без расширения>")
            for f in certs_path.iterdir() if f.is_file()
        })
        if present:
            logger.error(
                "cert_sync: в %s нет ни одного файла '%s'. "
                "Найденные расширения: %s. Похоже на неверный certs_dir/"
                "cert_extension — синхронизация сертификатов не выполняется.",
                certs_dir, CERT_EXTENSION, ", ".join(present),
            )
        else:
            logger.warning("cert_sync: каталог %s пуст", certs_dir)

    return [str(f) for f in cert_files]


def _upsert_account(db, cert_info: dict, stats: dict) -> None:
    """Создаёт или обновляет account по паре (cn, serial_number), коммитит.

    Коммит выполняется здесь, чтобы конфликт одной записи не откатывал батч.
    """
    existing = db.query(Account).filter_by(
        cn=cert_info['cn'],
        serial_number=cert_info['serial_number'],
    ).first()

    if existing is None:
        logger.info(
            "Creating new account: CN='%s', serial='%s'",
            cert_info['cn'], cert_info['serial_number'],
        )
        db.add(Account(
            cn=cert_info['cn'],
            serial_number=cert_info['serial_number'],
            valid_from=cert_info['valid_from'],
            valid_to=cert_info['valid_to'],
        ))
        db.commit()
        stats['created'] += 1
    else:
        existing.valid_from = cert_info['valid_from']
        existing.valid_to = cert_info['valid_to']
        db.commit()
        stats['updated'] += 1


def _recover_after_race(db, cert_info: dict, stats: dict) -> None:
    """После IntegrityError (гонка с client_connect) переоткрывает запись и
    обновляет даты сертификата. Если восстановиться не удалось — errors."""
    try:
        acct = db.query(Account).filter_by(
            cn=cert_info['cn'],
            serial_number=cert_info['serial_number'],
        ).first()
        if acct is not None:
            acct.valid_from = cert_info['valid_from']
            acct.valid_to = cert_info['valid_to']
            db.commit()
            stats['updated'] += 1
            logger.info(
                "Гонка с client_connect по CN='%s' serial='%s' — запись обновлена",
                cert_info['cn'], cert_info['serial_number'],
            )
        else:
            db.rollback()
            stats['errors'] += 1
    except Exception as e:
        db.rollback()
        stats['errors'] += 1
        logger.exception("Не удалось восстановиться после гонки: %s", e)


def sync_certificates(db=None, certs_dir: str = None, crl_path: str = None) -> dict:
    """
    Синхронизирует сертификаты с БД.

    Сканирует директорию с сертификатами:
    1. Парсит CRL для определения отозванных сертификатов
    2. Для каждого сертификата:
       - Если отозван: пропускает (не создаем account)
       - Если не отозван: создает или обновляет account
    3. Обновляет valid_from, valid_to для всех найденных

    Args:
        db: Сессия базы данных (если None, создается новая)
        certs_dir: Директория с сертификатами (если None, используется CERTS_DIR)
        crl_path: Путь к CRL файлу (если None, используется CRL_FILE)

    Returns:
        dict: Статистика синхронизации:
            - processed: количество обработанных сертификатов
            - created: количество созданных accounts
            - updated: количество обновленных записей
            - skipped_revoked: количество пропущенных отозванных
            - errors: количество ошибок

    Invariants: I6.1, I6.4, I6.5
    """
    stats = {
        'processed': 0,
        'created': 0,
        'updated': 0,
        'skipped_revoked': 0,
        'errors': 0,
    }

    # Используем переданные пути или дефолтные
    target_certs_dir = certs_dir or CERTS_DIR
    target_crl_path = crl_path or CRL_FILE

    logger.info("=" * 60)
    logger.info("Starting certificate synchronization")
    logger.info(f"Certificates directory: {target_certs_dir}")
    logger.info(f"CRL file: {target_crl_path}")

    # Парсим CRL для получения отозванных серийных номеров
    revoked_serials = parse_crl(target_crl_path)

    # Находим все сертификаты
    cert_files = find_cert_files(target_certs_dir)
    logger.info(f"Found {len(cert_files)} certificate files to process")

    # Создаем сессию БД если не передана
    close_db = False
    if db is None:
        logger.debug("Creating new database session")
        db = SessionLocal()
        close_db = True
    else:
        logger.debug("Using provided database session")

    try:
        for cert_path in cert_files:
            stats['processed'] += 1
            logger.debug(f"Processing certificate {stats['processed']}/{len(cert_files)}: {cert_path}")

            # Извлекаем информацию из сертификата
            cert_info = extract_cert_info(cert_path)
            if cert_info is None:
                stats['errors'] += 1
                logger.error(f"Failed to parse certificate: {cert_path}")
                continue

            # Проверяем, отозван ли сертификат
            if cert_info['serial_number'] in revoked_serials:
                # Пропускаем отозванные сертификаты
                stats['skipped_revoked'] += 1
                logger.info(f"Skipping revoked certificate: CN='{cert_info['cn']}', serial='{cert_info['serial_number']}'")
                continue

            # I6.5: Используем INSERT ... ON DUPLICATE KEY UPDATE для MySQL
            # или INSERT OR REPLACE для SQLite
            # Это позволяет создавать новые accounts или обновлять существующие
            # без дополнительных SELECT запросов
            # Теперь уникальность определяется парой (cn, serial_number)

            # Покоммитная обработка: один конфликтный/гоночный сертификат не
            # должен откатывать весь батч синхронизации (M2). Коммитим каждую
            # запись отдельно и восстанавливаемся после гонки с client_connect.
            try:
                _upsert_account(db, cert_info, stats)
            except IntegrityError:
                # Гонка: client_connect параллельно вставил (cn, serial).
                db.rollback()
                _recover_after_race(db, cert_info, stats)
            except Exception as e:
                db.rollback()
                stats['errors'] += 1
                logger.exception(
                    "Ошибка обработки сертификата CN='%s' serial='%s': %s",
                    cert_info['cn'], cert_info['serial_number'], e,
                )

        logger.info(
            f"Synchronization completed: "
            f"processed={stats['processed']}, "
            f"created={stats['created']}, "
            f"updated={stats['updated']}, "
            f"skipped_revoked={stats['skipped_revoked']}, "
            f"errors={stats['errors']}"
        )

    except Exception as e:
        db.rollback()
        logger.exception(f"Error during certificate sync: {e}")
        stats['errors'] += 1
    finally:
        if close_db:
            db.close()
            logger.debug("Database session closed")

    return stats


def main():
    """Точка входа для скрипта."""
    stats = sync_certificates()
    print(f"Certificate sync completed: {stats}")
    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
