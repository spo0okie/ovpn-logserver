"""
API endpoints для статистики.

I7.1: Только SELECT запросы к БД (агрегация COUNT, AVG и т.д.)
I7.2: Ответы соответствуют формату из api-design.md
I7.4: Фильтры и группировки работают как указано в спецификации
I7.6: Аутентификация обязательна (через Depends в main.py)
"""

from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, case

from core.models import Account, Session as SessionModel, ConnectionAttempt
from web.dependencies import get_db
from web.schemas import (
    OverviewStats,
    ConnectionsStatsResponse,
    FailuresStatsResponse,
    GeographyStatsResponse,
    ErrorResponse
)

router = APIRouter(tags=["stats"])


# =============================================================================
# Overview Stats
# =============================================================================

@router.get(
    "/stats/overview",
    response_model=OverviewStats,
    responses={401: {"model": ErrorResponse}}
)
def get_overview_stats(
    db: Session = Depends(get_db)
):
    """
    Общая статистика.

    Поддержка нескольких сертификатов на пользователя:
    - total_users: уникальные CN (пользователи)
    - total_certs: всего сертификатов
    - active_certs: активные сертификаты

    I7.1: Только SELECT запросы с агрегацией
    """
    # I7.1: Только SELECT запросы с COUNT
    # Статистика по аккаунтам (группировка по CN)
    total_users = db.query(func.count(distinct(Account.cn))).scalar() or 0
    total_certs = db.query(func.count(Account.id)).scalar() or 0
    active_certs = db.query(func.count(Account.id)).filter(
        Account.is_revoked == False
    ).scalar() or 0
    revoked_certs = db.query(func.count(Account.id)).filter(
        Account.is_revoked == True
    ).scalar() or 0

    # Пользователи с CCD (хотя бы один сертификат с has_ccd=True)
    with_ccd = db.query(func.count(distinct(Account.cn))).filter(
        Account.has_ccd == True
    ).scalar() or 0

    # Сертификаты, истекающие в ближайшие 30 дней
    soon = datetime.utcnow() + timedelta(days=30)
    expiring_soon = db.query(func.count(Account.id)).filter(
        Account.valid_to <= soon,
        Account.valid_to >= datetime.utcnow()
    ).scalar() or 0

    # Статистика по сессиям
    active_sessions = db.query(func.count(SessionModel.id)).filter(
        SessionModel.status == "active"
    ).scalar() or 0

    # Сессии за сегодня
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_sessions = db.query(func.count(SessionModel.id)).filter(
        SessionModel.connected_at >= today_start
    ).scalar() or 0

    # Сессии за неделю
    week_start = datetime.utcnow() - timedelta(days=7)
    week_sessions = db.query(func.count(SessionModel.id)).filter(
        SessionModel.connected_at >= week_start
    ).scalar() or 0

    # Сессии за месяц
    month_start = datetime.utcnow() - timedelta(days=30)
    month_sessions = db.query(func.count(SessionModel.id)).filter(
        SessionModel.connected_at >= month_start
    ).scalar() or 0

    # Статистика по попыткам
    failed_today = db.query(func.count(ConnectionAttempt.id)).filter(
        ConnectionAttempt.attempted_at >= today_start
    ).scalar() or 0

    failed_week = db.query(func.count(ConnectionAttempt.id)).filter(
        ConnectionAttempt.attempted_at >= week_start
    ).scalar() or 0

    return {
        "accounts": {
            "total_users": total_users,
            "total_certs": total_certs,
            "active_certs": active_certs,
            "revoked": revoked_certs,
            "with_ccd": with_ccd,
            "expiring_soon": expiring_soon
        },
        "sessions": {
            "active": active_sessions,
            "today": today_sessions,
            "this_week": week_sessions,
            "this_month": month_sessions
        },
        "attempts": {
            "failed_today": failed_today,
            "failed_this_week": failed_week
        }
    }


# =============================================================================
# Connections Stats
# =============================================================================

@router.get(
    "/stats/connections",
    response_model=ConnectionsStatsResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse}
    }
)
def get_connections_stats(
    from_date: datetime = Query(..., alias="from", description="Начало периода (обязательный)"),
    to_date: datetime = Query(..., alias="to", description="Конец периода (обязательный)"),
    group_by: str = Query("day", description="Группировка: hour, day, week, month"),
    db: Session = Depends(get_db)
):
    """
    Статистика подключений по времени.

    I7.4: Параметры from, to (обязательные), group_by
    I7.1: Только SELECT с агрегацией
    """
    # I7.4: Валидация group_by
    if group_by not in ["hour", "day", "week", "month"]:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid group_by parameter", "code": "INVALID_PARAMETER"}
        )

    # I7.1: Только SELECT запросы
    query = db.query(SessionModel).filter(
        SessionModel.connected_at >= from_date,
        SessionModel.connected_at <= to_date
    )

    # Получаем все сессии за период
    sessions = query.all()

    # Группируем по периоду
    from collections import defaultdict
    groups = defaultdict(lambda: {"connections": 0, "accounts": [], "durations": []})

    for session in sessions:
        # Определяем период
        if group_by == "hour":
            period = session.connected_at.strftime("%Y-%m-%d %H:00")
        elif group_by == "day":
            period = session.connected_at.strftime("%Y-%m-%d")
        elif group_by == "week":
            # Номер недели в году
            period = session.connected_at.strftime("%Y-W%W")
        else:  # month
            period = session.connected_at.strftime("%Y-%m")

        groups[period]["connections"] += 1
        groups[period]["accounts"].append(session.account_id)

        # Длительность сессии
        if session.disconnected_at and session.connected_at:
            duration = (session.disconnected_at - session.connected_at).total_seconds()
            groups[period]["durations"].append(duration)

    # Формируем ответ
    data = []
    for period in sorted(groups.keys()):
        info = groups[period]
        avg_duration = None
        if info["durations"]:
            avg_duration = int(sum(info["durations"]) / len(info["durations"]))

        data.append({
            "period": period,
            "connections": info["connections"],
            "unique_accounts": len(set(info["accounts"])),
            "avg_duration_seconds": avg_duration
        })

    return {
        "group_by": group_by,
        "data": data
    }


# =============================================================================
# Failures Stats
# =============================================================================

@router.get(
    "/stats/failures",
    response_model=FailuresStatsResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse}
    }
)
def get_failures_stats(
    from_date: datetime = Query(..., alias="from", description="Начало периода (обязательный)"),
    to_date: datetime = Query(..., alias="to", description="Конец периода (обязательный)"),
    group_by: str = Query("type", description="Группировка: type, day, account"),
    db: Session = Depends(get_db)
):
    """
    Статистика неудачных попыток.

    I7.4: Параметры from, to (обязательные), group_by
    I7.1: Только SELECT с агрегацией
    """
    # I7.4: Валидация group_by
    if group_by not in ["type", "day", "account"]:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid group_by parameter", "code": "INVALID_PARAMETER"}
        )

    # I7.1: Только SELECT запросы
    query = db.query(ConnectionAttempt).filter(
        ConnectionAttempt.attempted_at >= from_date,
        ConnectionAttempt.attempted_at <= to_date
    )

    attempts = query.all()
    total = len(attempts)

    if total == 0:
        return {
            "group_by": group_by,
            "data": []
        }

    from collections import defaultdict
    groups = defaultdict(int)

    for attempt in attempts:
        if group_by == "type":
            key = attempt.failure_type
        elif group_by == "day":
            key = attempt.attempted_at.strftime("%Y-%m-%d")
        else:  # account
            key = attempt.cert_cn or "unknown"

        groups[key] += 1

    # Формируем ответ
    result_data = []
    for key, count in sorted(groups.items(), key=lambda x: -x[1]):
        percentage = round((count / total) * 100, 1)
        result_data.append({
            "failure_type": str(key),
            "count": count,
            "percentage": percentage
        })

    return {
        "group_by": group_by,
        "data": result_data
    }


# =============================================================================
# Geography Stats
# =============================================================================

@router.get(
    "/stats/geography",
    response_model=GeographyStatsResponse,
    responses={401: {"model": ErrorResponse}}
)
def get_geography_stats(
    from_date: Optional[datetime] = Query(None, alias="from", description="Начало периода"),
    to_date: Optional[datetime] = Query(None, alias="to", description="Конец периода"),
    limit: int = Query(10, ge=1, le=100, description="Количество стран"),
    db: Session = Depends(get_db)
):
    """
    Статистика по геолокации.

    I7.4: Параметры from, to, limit
    I7.1: Только SELECT с агрегацией
    """
    # I7.1: Только SELECT запросы
    query = db.query(
        SessionModel.country,
        func.count(SessionModel.id).label("connections"),
        func.count(distinct(SessionModel.account_id)).label("unique_accounts")
    ).filter(
        SessionModel.country.isnot(None)
    )

    # I7.4: Применяем фильтры по дате если указаны
    if from_date:
        query = query.filter(SessionModel.connected_at >= from_date)
    if to_date:
        query = query.filter(SessionModel.connected_at <= to_date)

    # Группируем по стране
    query = query.group_by(SessionModel.country).order_by(func.count(SessionModel.id).desc())

    # Ограничиваем количество
    results = query.limit(limit).all()

    # Считаем общее количество для процентов
    total_query = db.query(func.count(SessionModel.id)).filter(
        SessionModel.country.isnot(None)
    )
    if from_date:
        total_query = total_query.filter(SessionModel.connected_at >= from_date)
    if to_date:
        total_query = total_query.filter(SessionModel.connected_at <= to_date)

    total = total_query.scalar() or 0

    # Формируем ответ
    data = []
    for country, connections, unique_accounts in results:
        percentage = round((connections / total) * 100, 1) if total > 0 else 0

        # Получаем код страны (если есть в GeoIPCache)
        # Для простоты считаем, что код может быть None
        data.append({
            "country": country,
            "country_code": None,  # Можно доработать с GeoIPCache
            "connections": connections,
            "unique_accounts": unique_accounts,
            "percentage": percentage
        })

    return {
        "data": data
    }
