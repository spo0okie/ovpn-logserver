"""
Тесты для SQLAlchemy моделей.

Проверяют инварианты I2.1-I2.5:
- I2.1: Модели наследуются от declarative_base()
- I2.2: Имена таблиц и полей совпадают со схемой БД
- I2.3: Типы данных в моделях соответствуют SQL типам
- I2.4: Отношения (relationship) настроены корректно
- I2.5: Ограничения БД (I1.1-I1.4) работают через ORM
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import inspect, Integer, BigInteger, String, DateTime, Boolean, Text, Enum, Numeric
from sqlalchemy.dialects.mysql import INTEGER, BIGINT
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.database import Base
from core.models import Account, Session as SessionModel, GeoIPCache


# ============================================================================
# Тесты инварианта I2.1: Модели наследуются от declarative_base()
# ============================================================================

class TestI21BaseInheritance:
    """Тесты проверяют, что все модели наследуются от declarative_base()."""
    
    def test_account_inherits_from_base(self):
        """Account должен наследоваться от Base."""
        assert issubclass(Account, Base)
        assert Account.__base__ is Base
    
    def test_session_inherits_from_base(self):
        """Session должен наследоваться от Base."""
        assert issubclass(SessionModel, Base)
        assert SessionModel.__base__ is Base
    
    
    def test_geoip_cache_inherits_from_base(self):
        """GeoIPCache должен наследоваться от Base."""
        assert issubclass(GeoIPCache, Base)
        assert GeoIPCache.__base__ is Base
    
    def test_all_models_in_base_metadata(self):
        """Все модели должны быть зарегистрированы в Base.metadata."""
        table_names = Base.metadata.tables.keys()
        assert "accounts" in table_names
        assert "sessions" in table_names
        assert "geoip_cache" in table_names


# ============================================================================
# Тесты инварианта I2.2: Имена таблиц и полей совпадают со схемой БД
# ============================================================================

class TestI22TableAndColumnNames:
    """Тесты проверяют соответствие имен таблиц и полей схеме БД."""
    
    # --- Тесты имен таблиц ---
    
    def test_account_tablename(self):
        """Имя таблицы Account должно быть 'accounts'."""
        assert Account.__tablename__ == "accounts"
    
    def test_session_tablename(self):
        """Имя таблицы Session должно быть 'sessions'."""
        assert SessionModel.__tablename__ == "sessions"
    
    
    def test_geoip_cache_tablename(self):
        """Имя таблицы GeoIPCache должно быть 'geoip_cache'."""
        assert GeoIPCache.__tablename__ == "geoip_cache"
    
    # --- Тесты имен полей Account ---

    def test_account_column_names(self):
        """Account должен иметь все поля из схемы БД."""
        mapper = inspect(Account)
        column_names = {col.name for col in mapper.columns}
        expected = {
            "id", "cn", "serial_number", "valid_from", "valid_to", "is_revoked",
            "revoked_at", "has_ccd", "ccd_updated_at", "created_at", "updated_at"
        }
        assert column_names == expected
    
    # --- Тесты имен полей Session ---
    
    def test_session_column_names(self):
        """Session должен иметь все поля из схемы БД."""
        mapper = inspect(SessionModel)
        column_names = {col.name for col in mapper.columns}
        expected = {
            "id", "account_id", "session_id", "connected_at", "disconnected_at",
            "source_ip", "country", "city", "bytes_sent", "bytes_received",
            "virtual_ip", "status", "created_at", "updated_at"
        }
        assert column_names == expected
    
    
    
    # --- Тесты имен полей GeoIPCache ---
    
    def test_geoip_cache_column_names(self):
        """GeoIPCache должен иметь все поля из схемы БД."""
        mapper = inspect(GeoIPCache)
        column_names = {col.name for col in mapper.columns}
        expected = {
            "ip", "country", "country_code", "city", "region",
            "latitude", "longitude", "isp", "cached_at", "expires_at"
        }
        assert column_names == expected


# ============================================================================
# Тесты инварианта I2.3: Типы данных соответствуют SQL типам
# ============================================================================

class TestI23ColumnTypes:
    """Тесты проверяют соответствие типов данных Python моделей SQL типам."""
    
    # --- Тесты типов Account ---
    
    def test_account_id_type(self):
        """Account.id должен быть Integer с autoincrement."""
        col = Account.__table__.c.id
        # Используем Integer для совместимости с SQLite (autoincrement работает только с Integer)
        assert isinstance(col.type, Integer)
    
    def test_account_cn_type(self):
        """Account.cn должен быть String(255)."""
        col = Account.__table__.c.cn
        assert isinstance(col.type, String)
        assert col.type.length == 255

    def test_account_serial_number_type(self):
        """Account.serial_number должен быть String(64)."""
        col = Account.__table__.c.serial_number
        assert isinstance(col.type, String)
        assert col.type.length == 64
    
    def test_account_valid_from_type(self):
        """Account.valid_from должен быть DateTime."""
        col = Account.__table__.c.valid_from
        assert isinstance(col.type, DateTime)
    
    def test_account_is_revoked_type(self):
        """Account.is_revoked должен быть Boolean."""
        col = Account.__table__.c.is_revoked
        assert isinstance(col.type, Boolean)
    
    def test_account_created_at_type(self):
        """Account.created_at должен быть DateTime."""
        col = Account.__table__.c.created_at
        assert isinstance(col.type, DateTime)
    
    # --- Тесты типов Session ---
    
    def test_session_id_type(self):
        """Session.id должен быть Integer с autoincrement."""
        col = SessionModel.__table__.c.id
        # Используем Integer для совместимости с SQLite (autoincrement работает только с Integer)
        assert isinstance(col.type, Integer)
    
    def test_session_account_id_type(self):
        """Session.account_id должен быть Integer."""
        col = SessionModel.__table__.c.account_id
        assert isinstance(col.type, Integer)
    
    def test_session_connected_at_type(self):
        """Session.connected_at должен быть DateTime."""
        col = SessionModel.__table__.c.connected_at
        assert isinstance(col.type, DateTime)
    
    def test_session_bytes_sent_type(self):
        """Session.bytes_sent должен быть Integer или BigInteger."""
        col = SessionModel.__table__.c.bytes_sent
        # Для SQLite используется Integer, для MySQL - BigInteger
        assert isinstance(col.type, (Integer, BigInteger))
    
    def test_session_status_type(self):
        """Session.status должен быть Enum."""
        col = SessionModel.__table__.c.status
        assert isinstance(col.type, Enum)
    
    
    
    
    
    # --- Тесты типов GeoIPCache ---
    
    def test_geoip_cache_latitude_type(self):
        """GeoIPCache.latitude должен быть Numeric(10, 8)."""
        col = GeoIPCache.__table__.c.latitude
        assert isinstance(col.type, Numeric)
        assert col.type.precision == 10
        assert col.type.scale == 8
    
    def test_geoip_cache_longitude_type(self):
        """GeoIPCache.longitude должен быть Numeric(11, 8)."""
        col = GeoIPCache.__table__.c.longitude
        assert isinstance(col.type, Numeric)
        assert col.type.precision == 11
        assert col.type.scale == 8


# ============================================================================
# Тесты инварианта I2.4: Отношения (relationship) настроены корректно
# ============================================================================

class TestI24Relationships:
    """Тесты проверяют корректность настройки relationship между моделями."""
    
    def test_account_has_sessions_relationship(self, db_session: Session, sample_account: Account, sample_session: SessionModel):
        """Account.sessions должен возвращать список сессий."""
        # Перезагружаем аккаунт из БД
        account = db_session.query(Account).filter_by(id=sample_account.id).first()
        
        # Проверяем, что sessions доступен
        assert hasattr(account, "sessions")
        
        # Загружаем сессии (dynamic relationship требует all())
        sessions = account.sessions.all()
        assert isinstance(sessions, list)
        assert len(sessions) == 1
        assert isinstance(sessions[0], SessionModel)
        assert sessions[0].id == sample_session.id
    
    def test_session_has_account_relationship(self, db_session: Session, sample_session: SessionModel):
        """Session.account должен возвращать связанный Account."""
        # Перезагружаем сессию из БД
        session = db_session.query(SessionModel).filter_by(id=sample_session.id).first()
        
        assert hasattr(session, "account")
        assert isinstance(session.account, Account)
        assert session.account.id == sample_session.account_id
    
    
    
    def test_cascade_delete_sessions(self, db_session: Session, sample_account: Account, sample_session: SessionModel):
        """При удалении Account должны удаляться связанные Session (CASCADE)."""
        account_id = sample_account.id
        session_id = sample_session.id
        
        # Удаляем аккаунт
        db_session.delete(sample_account)
        db_session.commit()
        
        # Проверяем, что сессия тоже удалена
        deleted_session = db_session.query(SessionModel).filter_by(id=session_id).first()
        assert deleted_session is None
    


# ============================================================================
# Тесты инварианта I2.5: Ограничения БД работают через ORM
# ============================================================================

class TestI25DatabaseConstraints:
    """Тесты проверяют, что ограничения БД (I1.1-I1.4) работают через ORM."""
    
    # --- Тест I1.1: UNIQUE KEY uk_cn_serial (cn, serial_number) ---

    def test_duplicate_cn_same_serial_raises_integrity_error(self, db_session: Session):
        """Создание аккаунта с дублирующейся парой (cn, serial_number) должно вызывать IntegrityError."""
        # Создаем первый аккаунт
        account1 = Account(cn="duplicate_test", serial_number="12345")
        db_session.add(account1)
        db_session.commit()

        # Пытаемся создать второй с тем же cn и serial_number
        account2 = Account(cn="duplicate_test", serial_number="12345")
        db_session.add(account2)

        # Должно выбросить IntegrityError
        with pytest.raises(IntegrityError):
            db_session.commit()

        # Откатываем транзакцию для чистоты
        db_session.rollback()

    def test_same_cn_different_serial_allowed(self, db_session: Session):
        """Создание аккаунтов с одним CN но разными serial_number должно быть разрешено."""
        # Создаем первый аккаунт
        account1 = Account(cn="multi_cert_user", serial_number="ABC123")
        db_session.add(account1)
        db_session.commit()

        # Создаем второй с тем же cn но другим serial_number
        account2 = Account(cn="multi_cert_user", serial_number="DEF456")
        db_session.add(account2)
        db_session.commit()

        # Проверяем что оба аккаунта созданы
        accounts = db_session.query(Account).filter_by(cn="multi_cert_user").all()
        assert len(accounts) == 2
        assert {a.serial_number for a in accounts} == {"ABC123", "DEF456"}

    def test_account_is_active_property(self, db_session: Session):
        """Проверка property is_active."""
        # Активный сертификат
        active_account = Account(
            cn="active_user",
            serial_number="ACTIVE001",
            is_revoked=False,
            valid_to=datetime.utcnow() + timedelta(days=30)
        )
        db_session.add(active_account)

        # Отозванный сертификат
        revoked_account = Account(
            cn="revoked_user",
            serial_number="REVOKED001",
            is_revoked=True,
            valid_to=datetime.utcnow() + timedelta(days=30)
        )
        db_session.add(revoked_account)

        # Истекший сертификат
        expired_account = Account(
            cn="expired_user",
            serial_number="EXPIRED001",
            is_revoked=False,
            valid_to=datetime.utcnow() - timedelta(days=1)
        )
        db_session.add(expired_account)

        db_session.commit()

        assert active_account.is_active is True
        assert revoked_account.is_active is False
        assert expired_account.is_active is False
    
    # --- Тест I1.2: NOT NULL ограничения ---
    
    def test_account_cn_not_null(self, db_session: Session):
        """Account.cn не может быть NULL."""
        account = Account(cn=None)
        db_session.add(account)
        
        with pytest.raises(IntegrityError):
            db_session.commit()
        
        db_session.rollback()
    
    def test_session_connected_at_not_null(self, db_session: Session, sample_account: Account):
        """Session.connected_at не может быть NULL."""
        session = SessionModel(
            account_id=sample_account.id,
            connected_at=None,  # Нарушаем NOT NULL
            source_ip="192.168.1.1"
        )
        db_session.add(session)
        
        with pytest.raises(IntegrityError):
            db_session.commit()
        
        db_session.rollback()
    
    def test_session_source_ip_not_null(self, db_session: Session, sample_account: Account):
        """Session.source_ip не может быть NULL."""
        session = SessionModel(
            account_id=sample_account.id,
            connected_at=datetime.utcnow(),
            source_ip=None  # Нарушаем NOT NULL
        )
        db_session.add(session)
        
        with pytest.raises(IntegrityError):
            db_session.commit()
        
        db_session.rollback()
    
    
    
    
    # --- Тест I1.3: FOREIGN KEY с ON DELETE CASCADE ---
    
    def test_session_account_id_foreign_key(self, db_session: Session):
        """Session.account_id должен иметь внешний ключ на accounts.id."""
        # Пытаемся создать сессию с несуществующим account_id
        session = SessionModel(
            account_id=99999,  # Несуществующий ID
            connected_at=datetime.utcnow(),
            source_ip="192.168.1.1"
        )
        db_session.add(session)
        
        with pytest.raises(IntegrityError):
            db_session.commit()
        
        db_session.rollback()
    
    # --- Тест I1.4: FOREIGN KEY с ON DELETE SET NULL ---
    
    


# ============================================================================
# Дополнительные тесты моделей
# ============================================================================

class TestModelBehavior:
    """Дополнительные тесты поведения моделей."""
    
    def test_account_repr(self):
        """Account.__repr__ должен возвращать корректную строку."""
        account = Account(id=1, cn="test_user")
        repr_str = repr(account)
        assert "Account" in repr_str
        assert "test_user" in repr_str
    
    def test_session_repr(self):
        """Session.__repr__ должен возвращать корректную строку."""
        session = SessionModel(id=1, account_id=1, status="active")
        repr_str = repr(session)
        assert "Session" in repr_str
        assert "active" in repr_str
    
    
    def test_geoip_cache_repr(self):
        """GeoIPCache.__repr__ должен возвращать корректную строку."""
        cache = GeoIPCache(ip="1.2.3.4", country="Test")
        repr_str = repr(cache)
        assert "GeoIPCache" in repr_str
        assert "1.2.3.4" in repr_str
    
    def test_geoip_cache_is_expired_false(self, sample_geoip_cache: GeoIPCache):
        """GeoIPCache.is_expired должен возвращать False для неистекшего кэша."""
        # expires_at установлен в будущем
        assert sample_geoip_cache.is_expired() is False
    
    def test_geoip_cache_is_expired_true(self, db_session: Session):
        """GeoIPCache.is_expired должен возвращать True для истекшего кэша."""
        cache = GeoIPCache(
            ip="9.9.9.9",
            expires_at=datetime.utcnow() - timedelta(days=1)  # Истек вчера
        )
        db_session.add(cache)
        db_session.commit()
        
        assert cache.is_expired() is True
    
    def test_geoip_cache_is_expired_no_expiry(self, db_session: Session):
        """GeoIPCache.is_expired должен возвращать False если expires_at is None."""
        cache = GeoIPCache(
            ip="8.8.4.4",
            expires_at=None
        )
        db_session.add(cache)
        db_session.commit()
        
        assert cache.is_expired() is False
    
    def test_session_default_status(self, db_session: Session, sample_account: Account):
        """Session.status по умолчанию должен быть 'active'."""
        session = SessionModel(
            account_id=sample_account.id,
            connected_at=datetime.utcnow(),
            source_ip="192.168.1.1"
            # status не указан
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)
        
        assert session.status == "active"
    
    
    def test_account_default_is_revoked(self, db_session: Session):
        """Account.is_revoked по умолчанию должен быть False."""
        account = Account(cn="test_default_revoked", serial_number="TEST001")
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)

        assert account.is_revoked is False

    def test_account_default_has_ccd(self, db_session: Session):
        """Account.has_ccd по умолчанию должен быть False."""
        account = Account(cn="test_default_ccd", serial_number="TEST002")
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)

        assert account.has_ccd is False

    def test_account_default_serial_number(self, db_session: Session):
        """Account.serial_number по умолчанию должен быть 'unknown'."""
        account = Account(cn="test_default_serial")
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)

        assert account.serial_number == "unknown"

    def test_account_repr_with_serial(self):
        """Account.__repr__ должен включать serial_number."""
        account = Account(id=1, cn="test_user", serial_number="ABC123")
        repr_str = repr(account)
        assert "Account" in repr_str
        assert "test_user" in repr_str
        assert "ABC123" in repr_str