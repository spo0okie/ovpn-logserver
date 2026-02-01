"""
Фикстуры для E2E тестов.

Содержит фикстуры для полного end-to-end тестирования системы.
"""

import os
import sys
import base64
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Устанавливаем тестовую БД ДО импорта core.database
TEST_E2E_DATABASE_URL = "sqlite:///./test_e2e.db"
os.environ["DATABASE_URL"] = TEST_E2E_DATABASE_URL

from core.database import Base, get_db
from core.models import Account, Session as SessionModel, ConnectionAttempt
from web.main import app


# Тестовая БД для E2E тестов
TEST_E2E_DATABASE_URL = os.getenv(
    "TEST_E2E_DATABASE_URL",
    "sqlite:///./test_e2e.db"
)


@pytest.fixture(scope="session")
def engine():
    """
    Создает engine для тестовой БД.
    
    Yields:
        Engine: SQLAlchemy engine
    """
    engine = create_engine(
        TEST_E2E_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    
    # Включаем поддержку внешних ключей для SQLite
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


@pytest.fixture(scope="function")
def api_client(db):
    """
    Создает тестовый клиент для API.
    
    Args:
        db: Сессия БД
    
    Yields:
        TestClient: Клиент для тестирования API
    """
    def _get_db_override():
        try:
            yield db
        finally:
            pass
    
    # Устанавливаем переменные окружения для авторизации
    os.environ["API_USERS"] = "admin:admin,test:test123"
    
    app.dependency_overrides[get_db] = _get_db_override
    
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
    credentials = base64.b64encode(b"admin:admin").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


class E2EVPNSimulator:
    """
    E2E симулятор VPN для полного цикла тестирования.
    
    Имитирует полный цикл работы системы:
    - Подключение клиента (client_connect)
    - Обновление данных в реальном времени
    - Отключение клиента (client_disconnect)
    - Синхронизация сертификатов
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
    
    def connect(self, cn: str, source_ip: str, virtual_ip: str = None, 
                country: str = None, city: str = None) -> dict:
        """
        Симулирует полное подключение клиента к VPN.
        
        Args:
            cn: Common Name сертификата
            source_ip: IP адрес клиента
            virtual_ip: Выделенный VPN IP (опционально)
            country: Страна для GeoIP (опционально)
            city: Город для GeoIP (опционально)
        
        Returns:
            dict: Информация о созданной сессии
        """
        self._session_counter += 1
        session_id = f"e2e_session_{self._session_counter}"
        
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
            'bytes_received': 0,
            'connected_at': datetime.utcnow()
        }
        
        # Вызываем client_connect с подменой окружения
        with patch.dict(os.environ, env_vars, clear=False):
            from collector.client_connect import create_or_get_account, create_session
            
            # Мокаем GeoIP если указаны страна/город
            if country or city:
                geo = {'country': country, 'city': city}
                account = create_or_get_account(self.db, cn)
                create_session(self.db, account.id, env_vars, geo)
            else:
                from core.geoip import resolve_geoip
                account = create_or_get_account(self.db, cn)
                geo = resolve_geoip(source_ip, self.db)
                create_session(self.db, account.id, env_vars, geo)
        
        return self._connected_users[cn]
    
    def disconnect(self, cn: str, bytes_sent: int = 1000, bytes_received: int = 2000,
                   duration: int = 3600):
        """
        Симулирует полное отключение клиента от VPN.
        
        Args:
            cn: Common Name сертификата
            bytes_sent: Отправлено байт
            bytes_received: Получено байт
            duration: Длительность сессии в секундах
        
        Returns:
            dict: Информация о закрытой сессии
        """
        if cn not in self._connected_users:
            return None
        
        user_info = self._connected_users[cn]
        
        # Устанавливаем переменные окружения как при реальном отключении
        env_vars = {
            'common_name': cn,
            'bytes_sent': str(bytes_sent),
            'bytes_received': str(bytes_received),
            'time_duration': str(duration)
        }
        
        # Вызываем client_disconnect с подменой окружения
        with patch.dict(os.environ, env_vars, clear=False):
            from collector.client_disconnect import close_active_session
            close_active_session(self.db, cn, bytes_sent, bytes_received)
        
        user_info['disconnected_at'] = datetime.utcnow()
        user_info['bytes_sent'] = bytes_sent
        user_info['bytes_received'] = bytes_received
        
        del self._connected_users[cn]
        return user_info
    
    def get_session_info(self, cn: str) -> dict:
        """
        Возвращает информацию о сессии пользователя.
        
        Args:
            cn: Common Name сертификата
        
        Returns:
            dict: Информация о сессии или None
        """
        return self._connected_users.get(cn)
    
    def is_connected(self, cn: str) -> bool:
        """
        Проверяет, подключен ли пользователь.
        
        Args:
            cn: Common Name сертификата
        
        Returns:
            bool: True если пользователь подключен
        """
        return cn in self._connected_users
    
    def get_active_count(self) -> int:
        """
        Возвращает количество активных сессий.
        
        Returns:
            int: Количество активных сессий
        """
        return len(self._connected_users)


@pytest.fixture
def e2e_vpn_simulator(db):
    """
    Создает E2E симулятор VPN.
    
    Args:
        db: Сессия БД
    
    Yields:
        E2EVPNSimulator: Экземпляр симулятора
    """
    simulator = E2EVPNSimulator(db)
    yield simulator


@pytest.fixture
def e2e_data_factory(db):
    """
    Фабрика для создания E2E тестовых данных.
    
    Args:
        db: Сессия БД
    
    Returns:
        E2EDataFactory: Фабрика тестовых данных
    """
    class E2EDataFactory:
        """Фабрика для создания комплексных E2E тестовых данных."""
        
        def __init__(self, db_session: Session):
            self.db = db_session
            self._counter = 0
        
        def create_complete_account(self, cn: str = None, **kwargs):
            """
            Создает полный аккаунт со всеми метаданными.
            
            Returns:
                Account: Созданный аккаунт
            """
            from core.models import Account
            
            self._counter += 1
            cn = cn or f"e2e_user_{self._counter}"
            
            account = Account(
                cn=cn,
                valid_from=kwargs.get('valid_from', datetime.utcnow() - timedelta(days=365)),
                valid_to=kwargs.get('valid_to', datetime.utcnow() + timedelta(days=365)),
                is_revoked=kwargs.get('is_revoked', False),
                has_ccd=kwargs.get('has_ccd', True),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self.db.add(account)
            self.db.commit()
            self.db.refresh(account)
            return account
        
        def create_session_history(self, account, num_sessions: int = 3):
            """
            Создает историю сессий для аккаунта.
            
            Args:
                account: Аккаунт
                num_sessions: Количество сессий
            
            Returns:
                list: Список созданных сессий
            """
            from core.models import Session as SessionModel
            
            sessions = []
            for i in range(num_sessions):
                self._counter += 1
                
                # Чередуем активные и закрытые сессии
                is_active = (i == num_sessions - 1)
                
                session = SessionModel(
                    account_id=account.id,
                    session_id=f"e2e_sess_{self._counter}",
                    connected_at=datetime.utcnow() - timedelta(days=num_sessions-i),
                    disconnected_at=None if is_active else datetime.utcnow() - timedelta(days=num_sessions-i-1),
                    source_ip=f"192.168.{self._counter//256}.{self._counter%256}",
                    country="Russia",
                    city="Moscow",
                    bytes_sent=1000 * (i + 1),
                    bytes_received=2000 * (i + 1),
                    virtual_ip=f"10.8.0.{self._counter}",
                    status="active" if is_active else "closed"
                )
                self.db.add(session)
                sessions.append(session)
            
            self.db.commit()
            for s in sessions:
                self.db.refresh(s)
            return sessions
        
        def create_failed_attempts(self, account=None, num_attempts: int = 3):
            """
            Создает историю неудачных попыток.
            
            Args:
                account: Аккаунт (опционально)
                num_attempts: Количество попыток
            
            Returns:
                list: Список созданных попыток
            """
            from core.models import ConnectionAttempt
            
            attempts = []
            failure_types = ["auth_failed", "cert_revoked", "ccd_missing"]
            
            for i in range(num_attempts):
                self._counter += 1
                
                attempt = ConnectionAttempt(
                    account_id=account.id if account else None,
                    attempted_at=datetime.utcnow() - timedelta(hours=i+1),
                    source_ip=f"10.0.{self._counter//256}.{self._counter%256}",
                    cert_cn=account.cn if account else f"unknown_{self._counter}",
                    failure_reason=f"E2E test failure {i}",
                    failure_type=failure_types[i % len(failure_types)],
                    details=f"E2E test details {i}"
                )
                self.db.add(attempt)
                attempts.append(attempt)
            
            self.db.commit()
            for a in attempts:
                self.db.refresh(a)
            return attempts
    
    return E2EDataFactory(db)
