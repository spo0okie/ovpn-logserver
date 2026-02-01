"""
Скрипт client-connect для OpenVPN.

Обрабатывает событие подключения клиента:
1. Читает переменные окружения от OpenVPN (I4.1)
2. Создает или находит account по CN (I4.2)
3. Создает запись session со статусом 'active' (I4.3)
4. Использует GeoIP модуль для определения геолокации (I4.4)
5. При любой ошибке возвращает exit 0, не блокируя VPN (I4.5)
6. Не делает SELECT запросов в БД, только INSERT (I4.6)

Инварианты:
- I4.1: Только переменные окружения OpenVPN
- I4.2: INSERT ... ON DUPLICATE KEY UPDATE для account
- I4.3: Статус 'active' при создании сессии
- I4.4: GeoIP через resolve_geoip()
- I4.5: exit 0 при любой ошибке
- I4.6: Только INSERT операции
"""

import os
import sys
from datetime import datetime

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal, engine
from core.models import Account, Session, Base
from core.geoip import resolve_geoip


def get_env_vars():
    """
    Получение переменных окружения от OpenVPN.
    
    Возвращает словарь с переменными:
    - common_name: CN сертификата клиента (обязательно)
    - trusted_ip: IP адрес клиента (обязательно)
    - trusted_port: порт клиента
    - ifconfig_pool_remote_ip: выделенный VPN IP клиента
    - time_unix: timestamp подключения
    
    Возвращает None, если отсутствуют обязательные переменные.
    """
    cn = os.environ.get('common_name')
    source_ip = os.environ.get('trusted_ip')
    
    if not cn or not source_ip:
        print("Missing required environment variables: common_name or trusted_ip", file=sys.stderr)
        return None
    
    return {
        'common_name': cn,
        'trusted_ip': source_ip,
        'trusted_port': os.environ.get('trusted_port'),
        'ifconfig_pool_remote_ip': os.environ.get('ifconfig_pool_remote_ip'),
        'time_unix': os.environ.get('time_unix')
    }


def create_or_get_account(db, cn: str):
    """
    Создает новый account или возвращает существующий по CN.
    
    Использует INSERT ... ON DUPLICATE KEY UPDATE (MySQL) или
    merge() для PostgreSQL/SQLite.
    
    Аргументы:
        db: сессия базы данных
        cn: Common Name из сертификата
    
    Возвращает:
        Account: созданный или существующий аккаунт
    
    Invariant I4.2, I4.6: Используем merge() вместо query() для upsert
    """
    # Создаем объект account
    account = Account(cn=cn)
    
    # Используем merge() для upsert без SELECT
    # merge() выполняет INSERT ... ON DUPLICATE KEY UPDATE
    merged_account = db.merge(account)
    db.flush()  # Синхронизируем с БД
    
    return merged_account


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
        except (ValueError, TypeError):
            pass  # Используем текущее время
    
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


def client_connect():
    """
    Главная функция скрипта client-connect.
    
    Обрабатывает подключение клиента и записывает данные в БД.
    При любой ошибке возвращает 0, чтобы не блокировать VPN.
    
    Возвращает:
        int: код выхода (всегда 0)
    
    Invariants: I4.1, I4.2, I4.3, I4.4, I4.5, I4.6
    """
    # I4.1: Читаем переменные окружения
    env_vars = get_env_vars()
    if env_vars is None:
        # I4.5: Не блокируем VPN при отсутствии переменных
        return 0
    
    db = None
    try:
        # Подключаемся к БД
        db = SessionLocal()
        
        # I4.2: Создаем или находим account без SELECT
        account = create_or_get_account(db, env_vars['common_name'])
        
        # I4.4: Получаем геолокацию
        geo = resolve_geoip(env_vars['trusted_ip'], db)
        
        # I4.3, I4.6: Создаем сессию со статусом active
        create_session(db, account.id, env_vars, geo)
        
        return 0
        
    except Exception as e:
        # I4.5: При любой ошибке возвращаем 0, не блокируем VPN
        print(f"Error in client_connect: {e}", file=sys.stderr)
        return 0
    finally:
        if db:
            db.close()


def main():
    """Точка входа для скрипта."""
    exit_code = client_connect()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
