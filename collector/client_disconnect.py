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
from datetime import datetime

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal, engine
from core.models import Account, Session, Base


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

    if not cn:
        print("Missing required environment variable: common_name", file=sys.stderr)
        return None

    # Парсим bytes_sent и bytes_received, по умолчанию 0
    try:
        bytes_sent = int(os.environ.get('bytes_sent', 0))
    except (ValueError, TypeError):
        bytes_sent = 0

    try:
        bytes_received = int(os.environ.get('bytes_received', 0))
    except (ValueError, TypeError):
        bytes_received = 0

    return {
        'common_name': cn,
        'bytes_sent': bytes_sent,
        'bytes_received': bytes_received,
        'time_duration': os.environ.get('time_duration')
    }


def close_active_session(db, cn: str, bytes_sent: int, bytes_received: int):
    """
    Закрывает последнюю активную сессию для указанного CN.

    Находит последнюю активную сессию (ORDER BY connected_at DESC LIMIT 1)
    и обновляет её:
    - disconnected_at = NOW()
    - status = 'closed'
    - bytes_sent = переданное значение
    - bytes_received = переданное значение

    Аргументы:
        db: сессия базы данных
        cn: Common Name из сертификата
        bytes_sent: количество отправленных байт
        bytes_received: количество полученных байт

    Invariants: I5.1, I5.2, I5.3, I5.4, I5.6
    """
    # I5.1: Находим последнюю активную сессию по CN
    # ORDER BY connected_at DESC LIMIT 1 - берем только последнюю
    active_session = db.query(Session).join(Account).filter(
        Account.cn == cn,
        Session.status == 'active'
    ).order_by(Session.connected_at.desc()).first()

    if active_session:
        # I5.2: Устанавливаем время отключения
        active_session.disconnected_at = datetime.utcnow()
        # I5.3: Меняем статус на 'closed'
        active_session.status = 'closed'
        # I5.4: Сохраняем статистику трафика
        active_session.bytes_sent = bytes_sent
        active_session.bytes_received = bytes_received
        # I5.6: Только UPDATE, никаких INSERT
        db.commit()


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
    # I5.1: Читаем переменные окружения
    env_vars = get_env_vars()
    if env_vars is None:
        # I5.5: Не блокируем VPN при отсутствии переменных
        return 0

    db = db_session
    should_close = False
    try:
        # Подключаемся к БД, если сессия не передана извне
        if db is None:
            db = SessionLocal()
            should_close = True

        # I5.1, I5.2, I5.3, I5.4, I5.6: Закрываем активную сессию
        close_active_session(
            db,
            env_vars['common_name'],
            env_vars['bytes_sent'],
            env_vars['bytes_received']
        )

        return 0

    except Exception as e:
        # I5.5: При любой ошибке возвращаем 0, не блокируем VPN
        print(f"Error in client_disconnect: {e}", file=sys.stderr)
        return 0
    finally:
        if should_close and db:
            db.close()


def main():
    """Точка входа для скрипта."""
    exit_code = client_disconnect()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
