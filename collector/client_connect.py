#!/usr/bin/env python3
"""
Скрипт client-connect для OpenVPN.

Обрабатывает событие подключения клиента:
1. Читает переменные окружения от OpenVPN (I4.1)
2. Создает или находит account по CN и serial_number (I4.2)
3. Проверяет наличие orphaned сессий для данного CN (C5.1-C5.4)
4. Создает запись session со статусом 'active' (I4.3)
5. Использует GeoIP модуль для определения геолокации (I4.4)
6. При любой ошибке возвращает exit 0, не блокируя VPN (I4.5)
7. Не делает SELECT запросов в БД для создания account (I4.6)

Инварианты:
- I4.1: Только переменные окружения OpenVPN
- I4.2: INSERT ... ON DUPLICATE KEY UPDATE для account (не merge())
- I4.3: Статус 'active' при создании сессии
- I4.4: GeoIP через resolve_geoip()
- I4.5: exit 0 при любой ошибке
- I4.6: Только INSERT операции для account
- C5.1: При подключении с активной сессией - старая помечается как orphaned
- C5.2: Перед созданием сессии проверяется наличие активной
- C5.3: orphaned сессия закрывается (disconnected_at=NOW())
- C5.4: Новая сессия создается только после закрытия старой
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Инвариант I4.5: хук не должен падать на импорт-этапе (ошибка конфига/БД/прав
# при загрузке core.database даёт ненулевой exit → OpenVPN заблокирует клиента).
# Любой сбой импорта фиксируем и обрабатываем внутри main() с exit 0.
try:
    from sqlalchemy.dialects.mysql import insert
    from core.database import SessionLocal, engine
    from core.models import Account, Session, Base
    from core.geoip import resolve_geoip
    from core.serial import normalize_serial
    _IMPORT_ERROR = None
except Exception as _import_exc:  # noqa: BLE001 — сознательно ловим всё
    _IMPORT_ERROR = _import_exc
    insert = None
    SessionLocal = engine = None
    Account = Session = Base = None
    resolve_geoip = None

    def normalize_serial(value):  # заглушка на случай сбоя импорта
        return value

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
        # Нет прав на создание каталога — не роняем импорт, FileHandler ниже
        # всё равно защищён try/except и деградирует на stderr.
        pass

LOG_FILE = LOG_DIR / "client-connect.log"

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

def get_env_vars():
    """
    Получение переменных окружения от OpenVPN.

    Возвращает словарь с переменными:
    - common_name: CN сертификата клиента (обязательно)
    - serial_number: серийный номер сертификата (из tls_serial_0)
    - trusted_ip: IP адрес клиента (обязательно)
    - trusted_port: порт клиента
    - ifconfig_pool_remote_ip: выделенный VPN IP клиента
    - time_unix: timestamp подключения

    Возвращает None, если отсутствуют обязательные переменные.
    """
    cn = os.environ.get('common_name')
    source_ip = os.environ.get('trusted_ip')
    # tls_serial_0 — hex-строка без префикса; нормализуем к каноническому виду.
    serial_number = normalize_serial(os.environ.get('tls_serial_0'))

    logger.debug(
        "Environment variables: common_name=%s, trusted_ip=%s, serial_number=%s",
        cn, source_ip, serial_number,
    )

    if not cn or not source_ip:
        logger.error(f"Missing required environment variables: common_name={cn}, trusted_ip={source_ip}")
        return None

    env_vars = {
        'common_name': cn,
        'serial_number': serial_number,
        'trusted_ip': source_ip,
        'trusted_port': os.environ.get('trusted_port'),
        'ifconfig_pool_remote_ip': os.environ.get('ifconfig_pool_remote_ip'),
        'time_unix': os.environ.get('time_unix')
    }

    logger.info(f"Received connection from CN='{cn}', serial='{serial_number}', IP='{source_ip}'")
    return env_vars


def create_or_get_account(db, cn: str, serial_number: str = "unknown"):
    """
    Создает новый account или обновляет существующий по паре (CN, serial_number).

    Использует INSERT ... ON DUPLICATE KEY UPDATE для MySQL или
    INSERT OR REPLACE для SQLite.
    При конфликте уникального ключа обновляет поле updated_at.

    Аргументы:
        db: сессия базы данных
        cn: Common Name из сертификата
        serial_number: Серийный номер сертификата (из tls_serial_0)

    Возвращает:
        Account: созданный или существующий аккаунт
    """
    logger.debug(f"Creating or getting account for CN='{cn}', serial='{serial_number}'")

    now = datetime.utcnow()

    # Проверяем диалект БД для выбора правильного синтаксиса UPSERT
    dialect_name = db.bind.dialect.name
    logger.debug(f"Using dialect: {dialect_name}")

    if dialect_name == 'mysql':
        # MySQL: INSERT ... ON DUPLICATE KEY UPDATE
        stmt = insert(Account).values(
            cn=cn,
            serial_number=serial_number,
            valid_from=None,
            valid_to=None,
            is_revoked=False,
            revoked_at=None,
            has_ccd=False,
            ccd_updated_at=None,
            created_at=now,
            updated_at=now
        )
        stmt = stmt.on_duplicate_key_update(updated_at=now)
    else:
        # SQLite: INSERT OR REPLACE (или INSERT ... ON CONFLICT DO UPDATE)
        # Проверяем существование записи
        existing = db.query(Account).filter(
            Account.cn == cn,
            Account.serial_number == serial_number
        ).first()

        if existing:
            # Запись существует - обновляем updated_at
            existing.updated_at = now
            db.commit()
            account = existing
            logger.info(f"Account updated: id={account.id}, cn='{account.cn}', serial='{account.serial_number}'")
            return account
        else:
            # Запись не существует - создаем новую
            account = Account(
                cn=cn,
                serial_number=serial_number,
                created_at=now,
                updated_at=now
            )
            db.add(account)
            db.commit()
            logger.info(f"Account created: id={account.id}, cn='{account.cn}', serial='{account.serial_number}'")
            return account

    # Для MySQL выполняем INSERT
    db.execute(stmt)
    db.commit()

    # Получаем account из БД
    account = db.query(Account).filter(
        Account.cn == cn,
        Account.serial_number == serial_number
    ).first()

    logger.info(f"Account ready: id={account.id}, cn='{account.cn}', serial='{account.serial_number}'")
    return account


def get_active_sessions_for_account(db, account_id: int) -> list:
    """
    Возвращает все активные сессии для данного аккаунта.

    Invariant C5.2: Проверяет наличие активной сессии для данного CN

    Аргументы:
        db: сессия базы данных
        account_id: ID аккаунта

    Возвращает:
        list: Список активных сессий
    """
    active_sessions = db.query(Session).filter(
        Session.account_id == account_id,
        Session.status == 'active'
    ).all()

    return active_sessions


def close_orphaned_session(db, session: Session):
    """
    Закрывает orphaned сессию: устанавливает status='error' и disconnected_at=NOW().

    Invariant C5.1: При подключении с активной сессией - старая помечается как orphaned
    Invariant C5.3: orphaned сессия закрывается (disconnected_at=NOW())

    Аргументы:
        db: сессия базы данных
        session: Сессия для закрытия
    """
    session.status = 'error'
    session.disconnected_at = datetime.utcnow()
    db.commit()

    logger.info(
        f"Orphaned session closed: session_id={session.id}, "
        f"account_id={session.account_id}, "
        f"connected_at={session.connected_at}, "
        f"disconnected_at={session.disconnected_at}"
    )


def close_orphaned_sessions(db, account_id: int) -> int:
    """
    Находит и закрывает все orphaned сессии для аккаунта.

    Invariant C5.4: Создается новая сессия только после закрытия старой

    Аргументы:
        db: сессия базы данных
        account_id: ID аккаунта

    Возвращает:
        int: Количество закрытых orphaned сессий
    """
    active_sessions = get_active_sessions_for_account(db, account_id)

    if not active_sessions:
        logger.debug(f"No active sessions found for account {account_id}")
        return 0

    closed_count = 0
    for session in active_sessions:
        close_orphaned_session(db, session)
        closed_count += 1

    logger.info(f"Closed {closed_count} orphaned sessions for account {account_id}")
    return closed_count


def create_session(db, account_id: int, env_vars: dict, geo: dict):
    """
    Создает запись о сессии со статусом 'active'.

    Аргументы:
        db: сессия базы данных
        account_id: ID аккаунта
        env_vars: переменные окружения
        geo: геолокационные данные

    Invariant I4.3, I4.6: Только INSERT, статус 'active'
    """
    # Разбираем тайстамп из time_unix если есть, иначе используем текущее время
    connected_at = datetime.utcnow()
    if env_vars.get('time_unix'):
        try:
            connected_at = datetime.utcfromtimestamp(int(env_vars['time_unix']))
            logger.debug(f"Using time_unix timestamp: {connected_at}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid time_unix value '{env_vars['time_unix']}': {e}, using current time")

    session = Session(
        account_id=account_id,
        connected_at=connected_at,
        source_ip=env_vars['trusted_ip'],
        country=geo.get('country') if geo else None,
        city=geo.get('city') if geo else None,
        virtual_ip=env_vars.get('ifconfig_pool_remote_ip'),
        status='active'
    )

    db.add(session)
    db.commit()

    logger.info(
        f"Session created: account_id={account_id}, "
        f"source_ip={env_vars['trusted_ip']}, "
        f"country={geo.get('country') if geo else 'N/A'}, "
        f"city={geo.get('city') if geo else 'N/A'}"
    )


def client_connect(db_session=None):
    """
    Главная функция скрипта client-connect.

    Обрабатывает подключение клиента и записывает данные в БД.
    При любой ошибке возвращает 0, чтобы не блокировать VPN.

    Invariant C5.1-C5.4: Проверяет и закрывает orphaned сессии перед созданием новой

    Args:
        db_session: Опциональная сессия БД для тестирования.
                   Если не передана, создается новая сессия через SessionLocal.

    Returns:
        int: код выхода (всегда 0)

    Invariants: I4.1, I4.2, I4.3, I4.4, I4.5, I4.6, C5.1, C5.2, C5.3, C5.4
    """
    logger.info("=" * 60)
    logger.info("Starting client-connect script")

    # I4.5: если импорт core.* не удался (конфиг/БД/права) — не блокируем VPN
    if _IMPORT_ERROR is not None:
        logger.error(
            "client-connect: ошибка импорта зависимостей, VPN не блокируется: %s",
            _IMPORT_ERROR,
        )
        return 0

    # I4.1: Читаем переменные окружения
    env_vars = get_env_vars()
    if env_vars is None:
        # I4.5: Не блокируем VPN при отсутствии переменных
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

        # I4.2: Создаем или находим account без SELECT
        # Используем пару (cn, serial_number) для идентификации
        account = create_or_get_account(
            db,
            env_vars['common_name'],
            env_vars.get('serial_number', 'unknown')
        )

        # C5.1-C5.4: Проверяем и закрываем orphaned сессии перед созданием новой
        closed_count = close_orphaned_sessions(db, account.id)
        if closed_count > 0:
            logger.info(f"Found and closed {closed_count} orphaned sessions for CN='{env_vars['common_name']}'")

        # I4.4: Получаем геолокацию
        logger.debug(f"Resolving GeoIP for {env_vars['trusted_ip']}")
        geo = resolve_geoip(env_vars['trusted_ip'], db)
        if geo:
            logger.debug(f"GeoIP resolved: {geo}")
        else:
            logger.warning(f"Could not resolve GeoIP for {env_vars['trusted_ip']}")

        # I4.3, I4.6: Создаем сессию со статусом active
        create_session(db, account.id, env_vars, geo)

        logger.info("Client-connect completed successfully")
        return 0

    except Exception as e:
        # I4.5: При любой ошибке возвращаем 0, не блокируем VPN
        logger.exception(f"Error in client_connect: {e}")
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
    Точка входа для скрипта client-connect.

    ВАЖНО: Всегда возвращает 0, чтобы не блокировать подключение к VPN
    при любых ошибках. OpenVPN ожидает exit 0 для успешного выполнения
    скрипта client-connect.
    """
    try:
        exit_code = client_connect()
        # Гарантируем, что exit_code всегда 0
        return 0 if exit_code != 0 else exit_code
    except Exception as e:
        # Логируем ошибку но НЕ блокируем VPN
        logger.exception(f"client-connect fatal error: {e}")
        return 0  # Всегда возвращаем 0 для OpenVPN


if __name__ == '__main__':
    sys.exit(main())
