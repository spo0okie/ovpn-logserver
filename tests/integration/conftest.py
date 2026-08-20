"""
Фикстуры для интеграционных тестов.

Содержит фикстуры для симуляции VPN подключений и полного цикла работы системы.
"""

import os
import sys
import tempfile
import base64
from datetime import datetime, timedelta
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Устанавливаем тестовую БД ДО импорта core.database.
# Корневой conftest.py уже выставил безопасный SQLite-дефолт, поэтому боевой
# конфиг сюда не попадёт даже если core.database импортирован раньше.
TEST_DATABASE_URL = "sqlite:///./test_integration.db"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# ВАЖНО: здесь раньше был importlib.reload(core.database / web.dependencies /
# web.main). Reload создаёт НОВЫЕ объекты функций get_db и НОВЫЙ app, из-за чего
# dependency_overrides, зарегистрированные в web/tests, переставали действовать —
# полный прогон падал, хотя пакеты по отдельности проходили. Вместо reload
# тесты работают со своим engine и подменяют зависимости FastAPI (см. ниже).

from core.database import Base, get_db, SessionLocal, engine as core_engine
from core.models import Account, Session as SessionModel
from web.dependencies import get_db as web_get_db
from web.main import app
from collector.client_connect import client_connect as collector_client_connect
from collector.client_disconnect import client_disconnect as collector_client_disconnect
from collector.cert_sync import sync_certificates

# Проверяем что используется SQLite
assert "sqlite" in str(core_engine.url).lower(), f"Expected SQLite, got {core_engine.url}"


# Тестовая БД для интеграционных тестов
TEST_DATABASE_URL = os.getenv(
    "TEST_INTEGRATION_DATABASE_URL",
    "sqlite:///./test_integration.db"
)


@pytest.fixture(scope="session")
def engine():
    """
    Создает engine для тестовой БД.
    
    Yields:
        Engine: SQLAlchemy engine
    """
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    
    # Включаем поддержку внешних ключей для SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Часть тестов (параллельные подключения, resilience) берёт сессию прямо из
    # core.database.SessionLocal в рантайме. Модульные engine/SessionLocal
    # создаются на этапе импорта и могут указывать на чужую тестовую БД, если
    # core.database импортирован раньше этого conftest. Перепривязываем их к
    # интеграционному engine — в отличие от importlib.reload это не создаёт
    # новых объектов функций/app и не ломает dependency_overrides в web-тестах.
    import core.database as core_db

    original_engine = core_db.engine
    original_session_local = core_db.SessionLocal

    core_db.engine = engine
    core_db.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield engine

    core_db.engine = original_engine
    core_db.SessionLocal = original_session_local
    engine.dispose()


@pytest.fixture(scope="function")
def tables(engine):
    """
    Создает таблицы перед тестом и удаляет после.
    
    Args:
        engine: SQLAlchemy engine
    
    Yields:
        None
    """
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db(engine, tables):
    """
    Создает сессию БД для теста.
    
    Для интеграционных тестов используем реальную БД (не транзакцию с rollback),
    чтобы API мог видеть данные.
    
    Args:
        engine: SQLAlchemy engine
        tables: Фикстура создания таблиц
    
    Yields:
        Session: SQLAlchemy сессия
    """
    # Создаем сессию напрямую через engine
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()


@pytest.fixture(scope="function")
def api_client(engine, tables):
    """
    Создает тестовый клиент для API.
    
    Args:
        engine: SQLAlchemy engine
        tables: Фикстура создания таблиц
    
    Yields:
        TestClient: Клиент для тестирования API
    """
    # Каждый запрос получает СВОЮ сессию — как в проде (get_db создаёт сессию
    # на запрос). Раньше все запросы делили один объект Session, а он не
    # потокобезопасен: тест с параллельными запросами падал примерно раз из трёх.
    Session = sessionmaker(bind=engine)

    def _get_db_override():
        request_db = Session()
        try:
            yield request_db
        finally:
            request_db.close()
    
    # Роуты зависят от web.dependencies.get_db — это другой объект функции,
    # чем core.database.get_db; FastAPI сопоставляет подмены по объекту.
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[web_get_db] = _get_db_override

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """
    Создает заголовки авторизации для API.
    
    Returns:
        dict: Заголовки с Basic Auth
    """
    # Используем учетные данные из config/auth.yaml
    credentials = base64.b64encode(b"admin:admin_password_123").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


class VPNSimulator:
    """
    Симулятор VPN подключений для тестирования.
    
    Имитирует поведение OpenVPN при подключении/отключении клиентов.
    """
    
    def __init__(self, db_session: Session):
        """
        Инициализация симулятора.
        
        Args:
            db_session: Сессия БД для записи данных
        """
        self.db = db_session
        self._connected_users = {}
        self._session_counter = 0
    
    def connect(self, cn: str, source_ip: str, virtual_ip: str = None) -> dict:
        """
        Симулирует подключение клиента к VPN.
        
        Args:
            cn: Common Name сертификата
            source_ip: IP адрес клиента
            virtual_ip: Выделенный VPN IP (опционально)
        
        Returns:
            dict: Информация о созданной сессии
        """
        self._session_counter += 1
        session_id = f"test_session_{self._session_counter}"
        
        # Устанавливаем переменные окружения как при реальном подключении
        env_vars = {
            'common_name': cn,
            'trusted_ip': source_ip,
            'trusted_port': '12345',
            'ifconfig_pool_remote_ip': virtual_ip or f"10.8.0.{self._session_counter}",
            'time_unix': str(int(datetime.utcnow().timestamp()))
        }
        
        # Сохраняем для отключения
        self._connected_users[cn] = {
            'session_id': session_id,
            'source_ip': source_ip,
            'virtual_ip': env_vars['ifconfig_pool_remote_ip'],
            'bytes_sent': 0,
            'bytes_received': 0
        }
        
        # Вызываем client_connect с подменой окружения
        with patch.dict(os.environ, env_vars, clear=False):
            # Создаем аккаунт и сессию напрямую через функции collector
            from collector.client_connect import create_or_get_account, create_session
            from core.geoip import resolve_geoip
            
            account = create_or_get_account(self.db, cn)
            geo = resolve_geoip(source_ip, self.db)
            create_session(self.db, account.id, env_vars, geo)
        
        return self._connected_users[cn]
    
    def disconnect(self, cn: str, bytes_sent: int = 1000, bytes_received: int = 2000):
        """
        Симулирует отключение клиента от VPN.
        
        Args:
            cn: Common Name сертификата
            bytes_sent: Отправлено байт
            bytes_received: Получено байт
        
        Returns:
            bool: True если отключение успешно
        """
        if cn not in self._connected_users:
            return False
        
        user_info = self._connected_users[cn]
        
        # Устанавливаем переменные окружения как при реальном отключении
        env_vars = {
            'common_name': cn,
            'bytes_sent': str(bytes_sent),
            'bytes_received': str(bytes_received),
            'time_duration': '3600'
        }
        
        # Вызываем client_disconnect с подменой окружения
        with patch.dict(os.environ, env_vars, clear=False):
            from collector.client_disconnect import close_active_session
            close_active_session(self.db, cn, bytes_sent, bytes_received)
        
        del self._connected_users[cn]
        return True
    
    def get_active_sessions(self) -> list:
        """
        Возвращает список активных сессий.
        
        Returns:
            list: Список активных сессий
        """
        return list(self._connected_users.keys())
    
    def is_connected(self, cn: str) -> bool:
        """
        Проверяет, подключен ли пользователь.
        
        Args:
            cn: Common Name сертификата
        
        Returns:
            bool: True если пользователь подключен
        """
        return cn in self._connected_users


@pytest.fixture
def vpn_simulator(db):
    """
    Создает симулятор VPN для тестирования.
    
    Args:
        db: Сессия БД
    
    Yields:
        VPNSimulator: Экземпляр симулятора
    """
    simulator = VPNSimulator(db)
    yield simulator


@pytest.fixture
def tmp_certs_dir(tmp_path):
    """
    Создает временную директорию для тестовых сертификатов.
    
    Args:
        tmp_path: Временный путь pytest
    
    Yields:
        Path: Путь к директории с сертификатами
    """
    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    yield certs_dir


def create_test_cert(certs_dir, cn: str, valid_days: int = 365):
    """
    Создает тестовый сертификат для интеграционных тестов.
    
    Args:
        certs_dir: Директория для сохранения сертификата
        cn: Common Name для сертификата
        valid_days: Срок действия в днях
    """
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import datetime, timedelta
    
    # Генерируем приватный ключ
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Создаем сертификат
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.utcnow()
    ).not_valid_after(
        datetime.utcnow() + timedelta(days=valid_days)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(cn)]),
        critical=False,
    ).sign(key, hashes.SHA256())
    
    # Сохраняем сертификат
    cert_path = certs_dir / f"{cn}.crt"
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    return cert_path


@pytest.fixture
def run_cert_sync(db):
    """
    Фикстура для запуска синхронизации сертификатов.
    
    Args:
        db: Сессия БД
    
    Returns:
        function: Функция для запуска синхронизации
    """
    def _run(certs_dir):
        return sync_certificates(db=db, certs_dir=str(certs_dir))
    return _run


@pytest.fixture
def sample_data_factory(db):
    """
    Фабрика для создания тестовых данных.
    
    Args:
        db: Сессия БД
    
    Returns:
        SampleDataFactory: Фабрика тестовых данных
    """
    class SampleDataFactory:
        """Фабрика для создания тестовых данных."""
        
        def __init__(self, db_session: Session):
            self.db = db_session
            self._counter = 0
        
        def create_account(self, cn: str = None, **kwargs) -> Account:
            """Создает тестовый аккаунт."""
            self._counter += 1
            cn = cn or f"test_user_{self._counter}"
            
            account = Account(
                cn=cn,
                valid_from=kwargs.get('valid_from', datetime.utcnow() - timedelta(days=365)),
                valid_to=kwargs.get('valid_to', datetime.utcnow() + timedelta(days=365)),
                is_revoked=kwargs.get('is_revoked', False),
                has_ccd=kwargs.get('has_ccd', False),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self.db.add(account)
            self.db.commit()
            self.db.refresh(account)
            return account
        
        def create_session(self, account: Account = None, status: str = "active", **kwargs) -> SessionModel:
            """Создает тестовую сессию."""
            if account is None:
                account = self.create_account()
            
            self._counter += 1
            session = SessionModel(
                account_id=account.id,
                session_id=kwargs.get('session_id', f"test_session_{self._counter}"),
                connected_at=kwargs.get('connected_at', datetime.utcnow() - timedelta(hours=1)),
                disconnected_at=kwargs.get('disconnected_at'),
                source_ip=kwargs.get('source_ip', f"192.168.1.{self._counter}"),
                country=kwargs.get('country', "Russia"),
                city=kwargs.get('city', "Moscow"),
                bytes_sent=kwargs.get('bytes_sent', 1000),
                bytes_received=kwargs.get('bytes_received', 2000),
                virtual_ip=kwargs.get('virtual_ip', f"10.8.0.{self._counter}"),
                status=status
            )
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)
            return session
        
    
    return SampleDataFactory(db)


@pytest.fixture
def restart_services(db, api_client):
    """
    Фикстура для симуляции перезапуска сервисов.
    
    Симулирует перезапуск путем очистки кэшей и пересоздания соединений.
    
    Args:
        db: Сессия БД
        api_client: Тестовый клиент API
    
    Returns:
        function: Функция для перезапуска сервисов
    """
    def _restart():
        # Очищаем dependency_overrides
        app.dependency_overrides.clear()
        
        # Пересоздаем соединение с БД
        db.close()
        
        # Восстанавливаем override
        def _get_db_override():
            try:
                yield db
            finally:
                pass
        
        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[web_get_db] = _get_db_override

        return True

    return _restart
