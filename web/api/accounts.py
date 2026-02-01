"""
API endpoints для работы с аккаунтами.

I7.1: Только SELECT запросы к БД
I7.2: Ответы соответствуют формату из api-design.md
I7.3: Пагинация работает корректно
I7.4: Фильтры работают как указано в спецификации
I7.5: При отсутствии данных возвращается 404 или пустой список
I7.6: Аутентификация обязательна (через Depends в main.py)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from core.models import Account, Session as SessionModel
from web.dependencies import get_db
from web.schemas import (
    AccountListResponse,
    AccountDetail,
    AccountLastSession,
    AccountSessionsResponse,
    AccountSessionItem,
    PaginationMeta,
    ErrorResponse
)

router = APIRouter(tags=["accounts"])


def _account_to_list_item(account: Account) -> dict:
    """Преобразует модель Account в словарь для списка."""
    return {
        "id": account.id,
        "cn": account.cn,
        "valid_from": account.valid_from,
        "valid_to": account.valid_to,
        "is_revoked": account.is_revoked,
        "has_ccd": account.has_ccd,
        "created_at": account.created_at
    }


def _can_connect(account: Account) -> bool:
    """Проверяет, может ли аккаунт подключаться."""
    if account.is_revoked:
        return False
    if account.valid_to and account.valid_to < datetime.utcnow():
        return False
    return True


@router.get(
    "/accounts",
    response_model=AccountListResponse,
    responses={401: {"model": ErrorResponse}}
)
def list_accounts(
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Элементов на страницу"),
    is_revoked: Optional[bool] = Query(None, description="Фильтр по статусу отзыва"),
    has_ccd: Optional[bool] = Query(None, description="Фильтр по наличию CCD"),
    search: Optional[str] = Query(None, description="Поиск по CN"),
    db: Session = Depends(get_db)
):
    """
    Список аккаунтов с пагинацией и фильтрами.

    I7.1: Только SELECT запросы
    I7.3: Пагинация через page/per_page
    I7.4: Фильтры is_revoked, has_ccd, search
    """
    # I7.1: Только SELECT запросы
    query = db.query(Account)

    # I7.4: Применяем фильтры
    if is_revoked is not None:
        query = query.filter(Account.is_revoked == is_revoked)
    if has_ccd is not None:
        query = query.filter(Account.has_ccd == has_ccd)
    if search:
        query = query.filter(Account.cn.ilike(f"%{search}%"))

    # I7.3: Пагинация
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    total_pages = (total + per_page - 1) // per_page

    return {
        "data": [_account_to_list_item(a) for a in items],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages
        }
    }


@router.get(
    "/accounts/{cn}",
    response_model=AccountDetail,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse}
    }
)
def get_account(
    cn: str,
    db: Session = Depends(get_db)
):
    """
    Детальная информация об аккаунте.

    I7.5: При отсутствии данных возвращается 404
    """
    # I7.1: Только SELECT запросы
    account = db.query(Account).filter(Account.cn == cn).first()

    # I7.5: 404 если аккаунт не найден
    if not account:
        raise HTTPException(
            status_code=404,
            detail={"error": "Account not found", "code": "ACCOUNT_NOT_FOUND"}
        )

    # Получаем последнюю сессию
    last_session = None
    latest_session = db.query(SessionModel).filter(
        SessionModel.account_id == account.id
    ).order_by(SessionModel.connected_at.desc()).first()

    if latest_session:
        last_session = {
            "id": latest_session.id,
            "status": latest_session.status,
            "connected_at": latest_session.connected_at,
            "disconnected_at": latest_session.disconnected_at,
            "is_active": latest_session.status == "active",
            "source_ip": latest_session.source_ip,
            "country": latest_session.country,
            "city": latest_session.city
        }

    return {
        "id": account.id,
        "cn": account.cn,
        "valid_from": account.valid_from,
        "valid_to": account.valid_to,
        "is_revoked": account.is_revoked,
        "revoked_at": account.revoked_at,
        "has_ccd": account.has_ccd,
        "can_connect": _can_connect(account),
        "created_at": account.created_at,
        "updated_at": account.updated_at,
        "last_session": last_session
    }


@router.get(
    "/accounts/{cn}/sessions",
    response_model=AccountSessionsResponse,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse}
    }
)
def get_account_sessions(
    cn: str,
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Элементов на страницу"),
    from_date: Optional[datetime] = Query(None, alias="from", description="Начало периода"),
    to_date: Optional[datetime] = Query(None, alias="to", description="Конец периода"),
    status: Optional[str] = Query(None, description="Фильтр по статусу (active, closed)"),
    db: Session = Depends(get_db)
):
    """
    История сессий аккаунта.

    I7.4: Фильтры from, to, status
    I7.5: 404 если аккаунт не найден
    """
    # I7.1: Только SELECT запросы
    # Сначала находим аккаунт
    account = db.query(Account).filter(Account.cn == cn).first()

    # I7.5: 404 если аккаунт не найден
    if not account:
        raise HTTPException(
            status_code=404,
            detail={"error": "Account not found", "code": "ACCOUNT_NOT_FOUND"}
        )

    # Получаем сессии аккаунта
    query = db.query(SessionModel).filter(SessionModel.account_id == account.id)

    # I7.4: Применяем фильтры
    if from_date:
        query = query.filter(SessionModel.connected_at >= from_date)
    if to_date:
        query = query.filter(SessionModel.connected_at <= to_date)
    if status:
        query = query.filter(SessionModel.status == status)

    query = query.order_by(SessionModel.connected_at.desc())

    # I7.3: Пагинация
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    total_pages = (total + per_page - 1) // per_page

    # Формируем ответ
    sessions_data = []
    for s in items:
        duration = None
        if s.disconnected_at and s.connected_at:
            duration = int((s.disconnected_at - s.connected_at).total_seconds())

        sessions_data.append({
            "id": s.id,
            "connected_at": s.connected_at,
            "disconnected_at": s.disconnected_at,
            "duration_seconds": duration,
            "source_ip": s.source_ip,
            "country": s.country,
            "city": s.city,
            "virtual_ip": s.virtual_ip,
            "status": s.status,
            "bytes_sent": s.bytes_sent,
            "bytes_received": s.bytes_received
        })

    return {
        "data": sessions_data,
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages
        }
    }
