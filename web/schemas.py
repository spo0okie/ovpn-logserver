"""
Pydantic схемы для API.

I7.2: Ответы соответствуют формату из api-design.md
"""

from datetime import datetime
from typing import Optional, List, Any, Dict

from pydantic import BaseModel, Field


# =============================================================================
# Meta схемы для пагинации (I7.3)
# =============================================================================

class PaginationMeta(BaseModel):
    """Метаданные пагинации для списковых ответов."""

    page: int = Field(..., description="Номер текущей страницы")
    per_page: int = Field(..., description="Количество элементов на страницу")
    total: int = Field(..., description="Общее количество элементов")
    total_pages: int = Field(..., description="Общее количество страниц")


class PaginatedResponse(BaseModel):
    """Базовая схема для пагинированного ответа."""

    data: List[Any] = Field(..., description="Список данных")
    meta: PaginationMeta = Field(..., description="Метаданные пагинации")


# =============================================================================
# Account схемы
# =============================================================================

class AccountBase(BaseModel):
    """Базовая схема аккаунта."""

    id: int
    cn: str
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_revoked: bool
    has_ccd: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AccountListItem(BaseModel):
    """Элемент списка аккаунтов."""

    id: int
    cn: str
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_revoked: bool
    has_ccd: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AccountLastSession(BaseModel):
    """Информация о последней сессии аккаунта."""

    id: int
    status: str
    connected_at: datetime
    disconnected_at: Optional[datetime] = None
    is_active: bool
    source_ip: str
    country: Optional[str] = None
    city: Optional[str] = None


class AccountDetail(BaseModel):
    """Детальная информация об аккаунте."""

    id: int
    cn: str
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_revoked: bool
    revoked_at: Optional[datetime] = None
    has_ccd: bool
    can_connect: bool
    created_at: datetime
    updated_at: datetime
    last_session: Optional[AccountLastSession] = None


class AccountListResponse(BaseModel):
    """Ответ списка аккаунтов."""

    data: List[AccountListItem]
    meta: PaginationMeta


# =============================================================================
# Session схемы
# =============================================================================

class GeoInfo(BaseModel):
    """Гео-информация."""

    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class SessionListItem(BaseModel):
    """Элемент списка сессий."""

    id: int
    account_cn: str
    connected_at: datetime
    disconnected_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    source_ip: str
    geo: GeoInfo
    virtual_ip: Optional[str] = None
    status: str
    bytes_sent: int
    bytes_received: int


class SessionDetail(BaseModel):
    """Детальная информация о сессии."""

    id: int
    account_cn: str
    session_id: Optional[str] = None
    connected_at: datetime
    disconnected_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    is_active: bool
    source_ip: str
    geo: GeoInfo
    virtual_ip: Optional[str] = None
    bytes_sent: int
    bytes_received: int
    status: str
    created_at: datetime
    updated_at: datetime


class ActiveSessionItem(BaseModel):
    """Элемент списка активных сессий."""

    id: int
    account_cn: str
    connected_at: datetime
    source_ip: str
    country: Optional[str] = None
    city: Optional[str] = None
    virtual_ip: Optional[str] = None


class ActiveSessionsResponse(BaseModel):
    """Ответ списка активных сессий."""

    count: int
    data: List[ActiveSessionItem]


class SessionListResponse(BaseModel):
    """Ответ списка сессий."""

    data: List[SessionListItem]
    meta: PaginationMeta


class AccountSessionItem(BaseModel):
    """Элемент истории сессий аккаунта."""

    id: int
    connected_at: datetime
    disconnected_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    source_ip: str
    country: Optional[str] = None
    city: Optional[str] = None
    virtual_ip: Optional[str] = None
    status: str
    bytes_sent: int
    bytes_received: int


class AccountSessionsResponse(BaseModel):
    """Ответ истории сессий аккаунта."""

    data: List[AccountSessionItem]
    meta: PaginationMeta


# =============================================================================
# Connection Attempt схемы
# =============================================================================

class AttemptAccountInfo(BaseModel):
    """Информация об аккаунте в попытке подключения."""

    cn: Optional[str] = None
    prefix: Optional[str] = None


class AttemptListItem(BaseModel):
    """Элемент списка попыток подключения."""

    id: int
    account: AttemptAccountInfo
    attempted_at: datetime
    source_ip: str
    cert_cn: Optional[str] = None
    failure_reason: str
    failure_type: str
    details: Optional[str] = None


class AttemptListResponse(BaseModel):
    """Ответ списка попыток подключения."""

    data: List[AttemptListItem]
    meta: PaginationMeta


# =============================================================================
# Statistics схемы
# =============================================================================

class AccountsStats(BaseModel):
    """Статистика аккаунтов."""

    total: int
    active_certs: int
    revoked: int
    with_ccd: int
    expiring_soon: int


class SessionsStats(BaseModel):
    """Статистика сессий."""

    active: int
    today: int
    this_week: int
    this_month: int


class AttemptsStats(BaseModel):
    """Статистика попыток."""

    failed_today: int
    failed_this_week: int


class OverviewStats(BaseModel):
    """Общая статистика."""

    accounts: AccountsStats
    sessions: SessionsStats
    attempts: AttemptsStats


class ConnectionPeriodStats(BaseModel):
    """Статистика подключений за период."""

    period: str
    connections: int
    unique_accounts: int
    avg_duration_seconds: Optional[int] = None


class ConnectionsStatsResponse(BaseModel):
    """Ответ статистики подключений."""

    group_by: str
    data: List[ConnectionPeriodStats]


class FailureTypeStats(BaseModel):
    """Статистика по типу ошибки."""

    failure_type: str
    count: int
    percentage: float


class FailuresStatsResponse(BaseModel):
    """Ответ статистики ошибок."""

    group_by: str
    data: List[FailureTypeStats]


class GeographyStatsItem(BaseModel):
    """Элемент статистики по геолокации."""

    country: str
    country_code: Optional[str] = None
    connections: int
    unique_accounts: int
    percentage: float


class GeographyStatsResponse(BaseModel):
    """Ответ статистики по геолокации."""

    data: List[GeographyStatsItem]


# =============================================================================
# Error схемы
# =============================================================================

class ErrorResponse(BaseModel):
    """Схема ошибки API."""

    error: str
    code: str
