"""
Фикстуры для тестов web модуля.
"""

import base64
import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Настраиваем тестовую БД
os.environ["DATABASE_URL"] = "sqlite:///./test_web.db"
os.environ["API_USERS"] = "admin:admin,test:test123"

from core.database import Base, get_db
from core.models import Account, Session as SessionModel, ConnectionAttempt
from web.main import app


# Создаем тестовый engine
engine = create_engine(
    "sqlite:///./test_web.db",
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Переопределение get_db для тестов."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def db():
    """Фикстура для создания тестовой БД."""
    # Создаем таблицы
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Очищаем таблицы
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Фикстура для TestClient."""
    def _get_db_override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Фикстура для заголовков авторизации."""
    credentials = base64.b64encode(b"admin:admin").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


@pytest.fixture
def sample_account(db: Session):
    """Создает тестовый аккаунт."""
    account = Account(
        cn="test_user",
        valid_from=datetime.utcnow() - timedelta(days=365),
        valid_to=datetime.utcnow() + timedelta(days=365),
        is_revoked=False,
        has_ccd=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture
def sample_accounts(db: Session):
    """Создает несколько тестовых аккаунтов."""
    accounts = []
    for i in range(5):
        account = Account(
            cn=f"user_{i}",
            valid_from=datetime.utcnow() - timedelta(days=365),
            valid_to=datetime.utcnow() + timedelta(days=365),
            is_revoked=i % 2 == 0,  # Чередуем отозванные
            has_ccd=i % 2 == 1,  # Чередуем с CCD
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(account)
        accounts.append(account)
    db.commit()
    for a in accounts:
        db.refresh(a)
    return accounts


@pytest.fixture
def sample_sessions(db: Session, sample_account: Account):
    """Создает тестовые сессии."""
    sessions = []

    # Активная сессия
    active = SessionModel(
        account_id=sample_account.id,
        session_id="sess_active",
        connected_at=datetime.utcnow() - timedelta(hours=1),
        source_ip="192.168.1.100",
        country="Russia",
        city="Moscow",
        bytes_sent=1000,
        bytes_received=2000,
        virtual_ip="10.8.0.5",
        status="active"
    )
    db.add(active)
    sessions.append(active)

    # Закрытая сессия
    closed = SessionModel(
        account_id=sample_account.id,
        session_id="sess_closed",
        connected_at=datetime.utcnow() - timedelta(days=1),
        disconnected_at=datetime.utcnow() - timedelta(hours=23),
        source_ip="192.168.1.101",
        country="Germany",
        city="Berlin",
        bytes_sent=5000,
        bytes_received=10000,
        virtual_ip="10.8.0.6",
        status="closed"
    )
    db.add(closed)
    sessions.append(closed)

    db.commit()
    for s in sessions:
        db.refresh(s)
    return sessions


@pytest.fixture
def sample_attempts(db: Session, sample_account: Account):
    """Создает тестовые попытки подключения."""
    attempts = []

    for i, ftype in enumerate(["auth_failed", "cert_revoked", "ccd_missing"]):
        attempt = ConnectionAttempt(
            account_id=sample_account.id if i % 2 == 0 else None,
            attempted_at=datetime.utcnow() - timedelta(hours=i),
            source_ip=f"10.0.0.{i}",
            cert_cn=sample_account.cn if i % 2 == 0 else "unknown_user",
            failure_reason=f"Test failure {i}",
            failure_type=ftype,
            details=f"Details {i}"
        )
        db.add(attempt)
        attempts.append(attempt)

    db.commit()
    for a in attempts:
        db.refresh(a)
    return attempts
