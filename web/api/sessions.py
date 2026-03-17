"""
API endpoints для работы с сессиями.

I7.1: Только SELECT запросы к БД
I7.2: Ответы соответствуют формату из api-design.md
I7.3: Пагинация работает корректно
I7.4: Фильтры работают как указано в спецификации
I7.5: При отсутствии данных возвращается 404 или пустой список
I7.6: Аутентификация обязательна (через Depends в main.py)
"""

from datetime import datetime
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from core.models import Account, Session as SessionModel
from web.dependencies import get_db
from web.schemas import (
    SessionListResponse,
    SessionDetail,
    ActiveSessionsResponse,
    PaginationMeta,
    ErrorResponse
)

router = APIRouter(tags=["sessions"])


def _session_to_list_item(session: SessionModel, account_cn: str) -> dict:
    """Преобразует модель Session в словарь для списка."""
    duration = None
    if session.disconnected_at and session.connected_at:
        duration = int((session.disconnected_at - session.connected_at).total_seconds())

    return {
        "id": session.id,
        "account_cn": account_cn,
        "connected_at": session.connected_at,
        "disconnected_at": session.disconnected_at,
        "duration_seconds": duration,
        "source_ip": session.source_ip,
        "geo": {
            "country": session.country,
            "country_code": None,  # Можно добавить из GeoIPCache если нужно
            "city": session.city
        },
        "virtual_ip": session.virtual_ip,
        "status": session.status,
        "bytes_sent": session.bytes_sent,
        "bytes_received": session.bytes_received
    }


@router.get(
    "/sessions",
    response_model=Union[SessionListResponse, dict],
    responses={401: {"model": ErrorResponse}}
)
def list_sessions(
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Элементов на страницу"),
    # Параметры для DataTable серверной обработки
    draw: Optional[int] = Query(None, description="DataTable draw counter"),
    search: Optional[str] = Query(None, description="DataTable глобальный поиск"),
    order_col: Optional[int] = Query(None, description="Номер колонки для сортировки"),
    order_dir: Optional[str] = Query(None, description="Направление сортировки"),
    # Стандартные фильтры
    account: Optional[str] = Query(None, description="Фильтр по CN аккаунта"),
    from_date: Optional[datetime] = Query(None, alias="from", description="Начало периода"),
    to_date: Optional[datetime] = Query(None, alias="to", description="Конец периода"),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    source_ip: Optional[str] = Query(None, description="Фильтр по IP"),
    country: Optional[str] = Query(None, description="Фильтр по стране"),
    db: Session = Depends(get_db)
):
    """
    Список всех сессий.

    I7.1: Только SELECT запросы
    I7.3: Пагинация через page/per_page
    I7.4: Фильтры account, from, to, status, source_ip, country
    Поддержка DataTable серверной обработки (search, order, pagination)
    """
    # I7.1: Только SELECT запросы
    query = db.query(SessionModel, Account.cn).join(
        Account, SessionModel.account_id == Account.id
    )

    # I7.4: Применяем фильтры из формы
    if account:
        query = query.filter(Account.cn == account)
    if from_date:
        query = query.filter(SessionModel.connected_at >= from_date)
    if to_date:
        query = query.filter(SessionModel.connected_at <= to_date)
    if status:
        query = query.filter(SessionModel.status == status)
    if source_ip:
        query = query.filter(SessionModel.source_ip == source_ip)
    if country:
        query = query.filter(SessionModel.country.ilike(f"%{country}%"))
    
    # DataTable глобальный поиск по всем столбцам
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                Account.cn.ilike(search_pattern),
                SessionModel.source_ip.ilike(search_pattern),
                SessionModel.virtual_ip.ilike(search_pattern),
                SessionModel.country.ilike(search_pattern),
                SessionModel.city.ilike(search_pattern)
            )
        )

    # Сортировка
    # NOTE: duration_seconds - вычисляемое поле, не колонка БД
    # Убрано из сортировки, т.к. оно вычисляется динамически из connected_at/disconnected_at
    order_columns = {
        0: SessionModel.id,
        1: Account.cn,
        2: SessionModel.connected_at,
        # 3: SessionModel.duration_seconds,  # <-- ERROR: attribute doesn't exist
        4: SessionModel.source_ip,
        5: SessionModel.country,
        6: SessionModel.virtual_ip,
        7: SessionModel.status
    }
    
    if order_col is not None:
        if order_col in order_columns:
            order_expr = order_columns[order_col]
            if order_dir == "desc":
                order_expr = order_expr.desc()
            query = query.order_by(order_expr)
        elif order_col == 3:  # duration_seconds - сортируем по connected_at desc как fallback
            query = query.order_by(SessionModel.connected_at.desc())
    else:
        query = query.order_by(SessionModel.connected_at.desc())

    # I7.3: Пагинация
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    total_pages = (total + per_page - 1) // per_page

    # Преобразуем данные
    data = [_session_to_list_item(s, cn) for s, cn in items]

    # Возвращаем DataTable-совместимый формат если передан draw
    if draw is not None:
        return {
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": total,
            "data": data
        }

    # Возвращаем стандартный формат с метаданными пагинации
    return {
        "data": data,
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages
        }
    }


@router.get(
    "/sessions/active",
    response_model=ActiveSessionsResponse,
    responses={401: {"model": ErrorResponse}}
)
def list_active_sessions(
    db: Session = Depends(get_db)
):
    """
    Список активных сессий.

    I7.4: Фильтр по статусу active
    """
    # I7.1: Только SELECT запросы
    query = db.query(SessionModel, Account.cn).join(
        Account, SessionModel.account_id == Account.id
    ).filter(SessionModel.status == "active").order_by(SessionModel.connected_at.desc())

    items = query.all()

    sessions_data = []
    for session, account_cn in items:
        sessions_data.append({
            "id": session.id,
            "account_cn": account_cn,
            "connected_at": session.connected_at,
            "source_ip": session.source_ip,
            "country": session.country,
            "city": session.city,
            "virtual_ip": session.virtual_ip
        })

    return {
        "count": len(sessions_data),
        "data": sessions_data
    }


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetail,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse}
    }
)
def get_session(
    session_id: int,
    db: Session = Depends(get_db)
):
    """
    Детали конкретной сессии.

    I7.5: При отсутствии данных возвращается 404
    """
    # I7.1: Только SELECT запросы
    result = db.query(SessionModel, Account.cn).join(
        Account, SessionModel.account_id == Account.id
    ).filter(SessionModel.id == session_id).first()

    # I7.5: 404 если сессия не найдена
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"error": "Session not found", "code": "SESSION_NOT_FOUND"}
        )

    session, account_cn = result

    # Вычисляем длительность
    duration = None
    if session.disconnected_at and session.connected_at:
        duration = int((session.disconnected_at - session.connected_at).total_seconds())

    return {
        "id": session.id,
        "account_cn": account_cn,
        "session_id": session.session_id,
        "connected_at": session.connected_at,
        "disconnected_at": session.disconnected_at,
        "duration_seconds": duration,
        "is_active": session.status == "active",
        "source_ip": session.source_ip,
        "geo": {
            "country": session.country,
            "country_code": None,
            "city": session.city,
            "region": None,
            "latitude": None,
            "longitude": None
        },
        "virtual_ip": session.virtual_ip,
        "bytes_sent": session.bytes_sent,
        "bytes_received": session.bytes_received,
        "status": session.status,
        "created_at": session.connected_at,  # Для сессий created_at = connected_at
        "updated_at": session.disconnected_at or session.connected_at
    }
