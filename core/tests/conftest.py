"""
Конфигурация pytest для тестов core модуля.

Содержит фикстуры для работы с БД в тестах.
"""

import os
import sys
from datetime import datetime, timedelta

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from core.database import Base
from core.models import Account, Session as SessionModel, GeoIPCache


# Используем SQLite в памяти для тестов (быстро и изолированно)
# Для MySQL-специфичных тестов можно использовать TEST_DATABASE_URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite:///:memory:"
)


@pytest.fixture(scope="session")
def engine():
    """
    Фикстура создает engine для тестовой БД.
    
    Yields:
        Engine: SQLAlchemy engine
    """
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {}
    )
    
    # Для SQLite включаем поддержку внешних ключей
    if "sqlite" in TEST_DATABASE_URL:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def tables(engine):
    """
    Фикстура создает все таблицы перед тестом и удаляет после.
    
    Args:
        engine: SQLAlchemy engine
    
    Yields:
        None
    """
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(engine, tables):
    """
    Фикстура создает сессию БД для теста.
    
    Автоматически откатывает транзакцию после теста.
    
    Args:
        engine: SQLAlchemy engine
        tables: Фикстура создания таблиц
    
    Yields:
        Session: SQLAlchemy сессия
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_account(db_session: Session) -> Account:
    """
    Фикстура создает тестовый аккаунт.

    Args:
        db_session: Сессия БД

    Returns:
        Account: Созданный аккаунт
    """
    account = Account(
        cn="test_user",
        serial_number="TEST001",
        valid_from=datetime.utcnow(),
        valid_to=datetime.utcnow() + timedelta(days=365),
        is_revoked=False,
        has_ccd=False
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


@pytest.fixture
def sample_session(db_session: Session, sample_account: Account) -> SessionModel:
    """
    Фикстура создает тестовую сессию.
    
    Args:
        db_session: Сессия БД
        sample_account: Тестовый аккаунт
    
    Returns:
        Session: Созданная сессия
    """
    session = SessionModel(
        account_id=sample_account.id,
        session_id="test_session_123",
        connected_at=datetime.utcnow(),
        source_ip="192.168.1.1",
        country="Russia",
        city="Moscow",
        bytes_sent=1000,
        bytes_received=2000,
        virtual_ip="10.8.0.2",
        status="active"
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session




@pytest.fixture
def sample_geoip_cache(db_session: Session) -> GeoIPCache:
    """
    Фикстура создает тестовую запись GeoIP кэша.
    
    Args:
        db_session: Сессия БД
    
    Returns:
        GeoIPCache: Созданная запись кэша
    """
    cache = GeoIPCache(
        ip="8.8.8.8",
        country="United States",
        country_code="US",
        city="Mountain View",
        region="California",
        latitude=37.386051,
        longitude=-122.083847,
        isp="Google LLC",
        cached_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30)
    )
    db_session.add(cache)
    db_session.commit()
    db_session.refresh(cache)
    return cache