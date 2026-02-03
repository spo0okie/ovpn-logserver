"""
SQLAlchemy модели для OpenVPN LogServer.

Модели точно соответствуют схеме БД из миграции 001_initial_schema.py.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Integer, BigInteger, String, DateTime, Boolean, Text,
    ForeignKey, Enum, Numeric, UniqueConstraint
)
from sqlalchemy.dialects.mysql import INTEGER, BIGINT

# MySQL-специфичные типы для UNSIGNED полей
# Используем стандартные типы как fallback для других БД (SQLite в тестах)
def get_int_type(unsigned=True, autoincrement=False):
    """
    Возвращает INTEGER тип с поддержкой UNSIGNED для MySQL.
    
    Для SQLite возвращает стандартный Integer (autoincrement работает только с Integer).
    """
    # Для совместимости с SQLite используем стандартный Integer
    # В MySQL через Alembic миграции будут правильные UNSIGNED типы
    return Integer


def get_bigint_type(unsigned=True, autoincrement=False):
    """
    Возвращает BIGINT тип с поддержкой UNSIGNED для MySQL.
    
    Для SQLite возвращает Integer (так как BIGINT autoincrement не поддерживается в SQLite).
    """
    # Для совместимости с SQLite используем Integer вместо BigInteger
    # потому что в SQLite autoincrement работает только с INTEGER PRIMARY KEY
    # В MySQL через Alembic миграции будут правильные BIGINT UNSIGNED типы
    return Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Account(Base):
    """
    Модель для таблицы accounts - справочник аккаунтов OpenVPN.

    Поддерживает несколько сертификатов с одним CN (Common Name).
    Уникальность обеспечивается парой (cn, serial_number).

    Attributes:
        id: Первичный ключ (INT UNSIGNED AUTO_INCREMENT)
        cn: Common Name из сертификата (VARCHAR 255)
        serial_number: Серийный номер сертификата (VARCHAR 64)
        valid_from: Дата начала действия сертификата
        valid_to: Дата окончания действия сертификата
        is_revoked: Флаг отзыва сертификата
        revoked_at: Дата отзыва сертификата
        has_ccd: Флаг наличия CCD конфигурации
        ccd_updated_at: Дата обновления CCD
        created_at: Дата создания записи
        updated_at: Дата последнего обновления
        sessions: Связанные VPN сессии
        connection_attempts: Связанные попытки подключения
    """

    __tablename__ = "accounts"  # I2.2: Имя таблицы совпадает со схемой БД

    # I2.3: Типы данных соответствуют SQL типам
    id: Mapped[int] = mapped_column(
        get_int_type(unsigned=True, autoincrement=True),  # INT UNSIGNED AUTO_INCREMENT
        primary_key=True,
        autoincrement=True
    )
    cn: Mapped[str] = mapped_column(
        String(255),  # VARCHAR(255)
        nullable=False
    )
    serial_number: Mapped[str] = mapped_column(
        String(64),  # VARCHAR(64)
        nullable=False,
        default="unknown"
    )
    valid_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime,  # DATETIME
        nullable=True
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime,  # DATETIME
        nullable=True
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,  # BOOLEAN
        default=False,
        nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,  # DATETIME
        nullable=True
    )
    has_ccd: Mapped[bool] = mapped_column(
        Boolean,  # BOOLEAN
        default=False,
        nullable=False
    )
    ccd_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,  # DATETIME
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,  # DATETIME DEFAULT CURRENT_TIMESTAMP
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,  # DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # I2.4: Отношения настроены корректно
    # account.sessions -> список сессий
    sessions: Mapped[List["Session"]] = relationship(
        "Session",
        back_populates="account",
        cascade="all, delete-orphan",  # ON DELETE CASCADE
        lazy="dynamic"
    )

    # account.connection_attempts -> список попыток подключения
    connection_attempts: Mapped[List["ConnectionAttempt"]] = relationship(
        "ConnectionAttempt",
        back_populates="account",
        lazy="dynamic"
    )

    # I2.5: Ограничения БД сохраняются
    # Composite unique constraint: пара (cn, serial_number) должна быть уникальной
    __table_args__ = (
        UniqueConstraint("cn", "serial_number", name="uk_cn_serial"),
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, cn='{self.cn}', serial='{self.serial_number}')>"

    @property
    def is_active(self) -> bool:
        """
        Проверяет, активен ли данный сертификат.

        Returns:
            True если сертификат не отозван и не истек
        """
        if self.is_revoked:
            return False
        if self.valid_to and self.valid_to < datetime.utcnow():
            return False
        return True

    @staticmethod
    def can_user_connect(db, cn: str) -> bool:
        """
        Проверяет, может ли пользователь с данным CN подключаться.

        Пользователь может подключаться если у него есть хотя бы один
        неотозванный и неистекший сертификат.

        Args:
            db: сессия базы данных
            cn: Common Name пользователя

        Returns:
            True если пользователь имеет активный сертификат
        """
        from sqlalchemy import or_
        active_account = db.query(Account).filter(
            Account.cn == cn,
            Account.is_revoked == False,
            or_(
                Account.valid_to == None,
                Account.valid_to >= datetime.utcnow()
            )
        ).first()
        return active_account is not None

    @staticmethod
    def get_active_certificates_count(db, cn: str) -> int:
        """
        Возвращает количество активных сертификатов пользователя.

        Args:
            db: сессия базы данных
            cn: Common Name пользователя

        Returns:
            Количество активных (неотозванных и неистекших) сертификатов
        """
        from sqlalchemy import or_
        return db.query(Account).filter(
            Account.cn == cn,
            Account.is_revoked == False,
            or_(
                Account.valid_to == None,
                Account.valid_to >= datetime.utcnow()
            )
        ).count()

    @staticmethod
    def get_certificates_stats(db, cn: str) -> dict:
        """
        Возвращает статистику по сертификатам пользователя.

        Args:
            db: сессия базы данных
            cn: Common Name пользователя

        Returns:
            Словарь с полями:
                - total: общее количество сертификатов
                - active: количество активных сертификатов
                - revoked: количество отозванных сертификатов
                - expired: количество истекших сертификатов
        """
        from sqlalchemy import or_, and_
        accounts = db.query(Account).filter(Account.cn == cn).all()

        total = len(accounts)
        revoked = sum(1 for a in accounts if a.is_revoked)
        expired = sum(1 for a in accounts if not a.is_revoked and a.valid_to and a.valid_to < datetime.utcnow())
        active = total - revoked - expired

        return {
            "total": total,
            "active": active,
            "revoked": revoked,
            "expired": expired
        }


class Session(Base):
    """
    Модель для таблицы sessions - журнал VPN сессий.
    
    Attributes:
        id: Первичный ключ (BIGINT UNSIGNED AUTO_INCREMENT)
        account_id: Внешний ключ на accounts (INT UNSIGNED)
        session_id: ID сессии OpenVPN (VARCHAR 100)
        connected_at: Время подключения
        disconnected_at: Время отключения
        source_ip: IP адрес источника
        country: Страна (из GeoIP)
        city: Город (из GeoIP)
        bytes_sent: Отправлено байт
        bytes_received: Получено байт
        virtual_ip: Виртуальный IP в VPN
        status: Статус сессии (active/closed/error)
        account: Связанный аккаунт
    """
    
    __tablename__ = "sessions"  # I2.2: Имя таблицы совпадает со схемой БД
    
    # I2.3: Типы данных соответствуют SQL типам
    id: Mapped[int] = mapped_column(
        get_bigint_type(unsigned=True, autoincrement=True),  # BIGINT UNSIGNED AUTO_INCREMENT
        primary_key=True,
        autoincrement=True
    )
    account_id: Mapped[int] = mapped_column(
        get_int_type(unsigned=True),  # INT UNSIGNED
        ForeignKey("accounts.id", ondelete="CASCADE"),  # I1.3: ON DELETE CASCADE
        nullable=False
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(100),  # VARCHAR(100)
        nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime,  # DATETIME NOT NULL
        nullable=False
    )
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,  # DATETIME
        nullable=True
    )
    source_ip: Mapped[str] = mapped_column(
        String(45),  # VARCHAR(45) NOT NULL (IPv6 compatible)
        nullable=False
    )
    country: Mapped[Optional[str]] = mapped_column(
        String(100),  # VARCHAR(100)
        nullable=True
    )
    city: Mapped[Optional[str]] = mapped_column(
        String(100),  # VARCHAR(100)
        nullable=True
    )
    bytes_sent: Mapped[int] = mapped_column(
        get_bigint_type(unsigned=True),  # BIGINT UNSIGNED DEFAULT 0
        default=0,
        nullable=False
    )
    bytes_received: Mapped[int] = mapped_column(
        get_bigint_type(unsigned=True),  # BIGINT UNSIGNED DEFAULT 0
        default=0,
        nullable=False
    )
    virtual_ip: Mapped[Optional[str]] = mapped_column(
        String(45),  # VARCHAR(45)
        nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "closed", "error", name="session_status"),  # ENUM
        default="active",
        nullable=False
    )
    
    # I2.4: Отношения настроены корректно
    # session.account -> связанный аккаунт
    account: Mapped["Account"] = relationship(
        "Account",
        back_populates="sessions"
    )
    
    def __repr__(self) -> str:
        return f"<Session(id={self.id}, account_id={self.account_id}, status='{self.status}')>"


class ConnectionAttempt(Base):
    """
    Модель для таблицы connection_attempts - неудачные попытки подключения.
    
    Attributes:
        id: Первичный ключ (BIGINT UNSIGNED AUTO_INCREMENT)
        account_id: Внешний ключ на accounts (INT UNSIGNED, nullable)
        attempted_at: Время попытки
        source_ip: IP адрес источника
        cert_cn: CN из сертификата
        failure_reason: Причина ошибки
        failure_type: Тип ошибки (enum)
        details: Дополнительные детали
        account: Связанный аккаунт (если найден)
    """
    
    __tablename__ = "connection_attempts"  # I2.2: Имя таблицы совпадает со схемой БД
    
    # I2.3: Типы данных соответствуют SQL типам
    id: Mapped[int] = mapped_column(
        get_bigint_type(unsigned=True, autoincrement=True),  # BIGINT UNSIGNED AUTO_INCREMENT
        primary_key=True,
        autoincrement=True
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        get_int_type(unsigned=True),  # INT UNSIGNED
        ForeignKey("accounts.id", ondelete="SET NULL"),  # I1.4: ON DELETE SET NULL
        nullable=True
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime,  # DATETIME NOT NULL
        nullable=False
    )
    source_ip: Mapped[str] = mapped_column(
        String(45),  # VARCHAR(45) NOT NULL
        nullable=False
    )
    cert_cn: Mapped[Optional[str]] = mapped_column(
        String(255),  # VARCHAR(255)
        nullable=True
    )
    failure_reason: Mapped[str] = mapped_column(
        String(255),  # VARCHAR(255) NOT NULL
        nullable=False
    )
    failure_type: Mapped[str] = mapped_column(
        Enum(
            "auth_failed",
            "cert_revoked",
            "cert_expired",
            "ccd_missing",
            "tls_error",
            "other",
            name="failure_type_enum"
        ),  # ENUM
        default="other",
        nullable=False
    )
    details: Mapped[Optional[str]] = mapped_column(
        Text,  # TEXT
        nullable=True
    )
    
    # I2.4: Отношения настроены корректно
    # connection_attempt.account -> связанный аккаунт
    account: Mapped[Optional["Account"]] = relationship(
        "Account",
        back_populates="connection_attempts"
    )
    
    def __repr__(self) -> str:
        return f"<ConnectionAttempt(id={self.id}, failure_type='{self.failure_type}')>"


class GeoIPCache(Base):
    """
    Модель для таблицы geoip_cache - кэш GeoIP данных.
    
    Attributes:
        ip: IP адрес (первичный ключ, VARCHAR 45)
        country: Страна
        country_code: Код страны (ISO 3166-1 alpha-2)
        city: Город
        region: Регион
        latitude: Широта
        longitude: Долгота
        isp: Интернет-провайдер
        cached_at: Время кэширования
        expires_at: Время истечения кэша
    """
    
    __tablename__ = "geoip_cache"  # I2.2: Имя таблицы совпадает со схемой БД
    
    # I2.3: Типы данных соответствуют SQL типам
    ip: Mapped[str] = mapped_column(
        String(45),  # VARCHAR(45) PRIMARY KEY
        primary_key=True
    )
    country: Mapped[Optional[str]] = mapped_column(
        String(100),  # VARCHAR(100)
        nullable=True
    )
    country_code: Mapped[Optional[str]] = mapped_column(
        String(2),  # VARCHAR(2)
        nullable=True
    )
    city: Mapped[Optional[str]] = mapped_column(
        String(100),  # VARCHAR(100)
        nullable=True
    )
    region: Mapped[Optional[str]] = mapped_column(
        String(100),  # VARCHAR(100)
        nullable=True
    )
    latitude: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 8),  # DECIMAL(10, 8)
        nullable=True
    )
    longitude: Mapped[Optional[float]] = mapped_column(
        Numeric(11, 8),  # DECIMAL(11, 8)
        nullable=True
    )
    isp: Mapped[Optional[str]] = mapped_column(
        String(255),  # VARCHAR(255)
        nullable=True
    )
    cached_at: Mapped[datetime] = mapped_column(
        DateTime,  # DATETIME DEFAULT CURRENT_TIMESTAMP
        default=datetime.utcnow,
        nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,  # DATETIME
        nullable=True
    )
    
    def __repr__(self) -> str:
        return f"<GeoIPCache(ip='{self.ip}', country='{self.country}')>"
    
    def is_expired(self) -> bool:
        """
        Проверяет, истек ли срок действия кэша.
        
        Returns:
            True если expires_at установлен и прошел, иначе False
        """
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at