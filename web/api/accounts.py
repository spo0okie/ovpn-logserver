"""
API endpoints для работы с аккаунтами.

I7.1: Только SELECT запросы к БД
I7.2: Ответы соответствуют формату из api-design.md
I7.3: Пагинация работает корректно
I7.4: Фильтры работают как указано в спецификации
I7.5: При отсутствии данных возвращается 404 или пустой список
I7.6: Аутентификация обязательна (через Depends в main.py)

Поддержка нескольких сертификатов на одного пользователя:
- Группировка по CN (одна запись на пользователя)
- Агрегированные данные о сертификатах
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_, and_, desc, asc

from core.models import Account, Session as SessionModel
from web.dependencies import get_db
from web.schemas import (
    AccountListResponse,
    AccountDetail,
    AccountLastSession,
    AccountSessionsResponse,
    AccountSessionItem,
    PaginationMeta,
    ErrorResponse,
    CertificateItem
)

router = APIRouter(tags=["accounts"])


def _can_user_connect(db: Session, cn: str) -> bool:
    """
    Проверяет, может ли пользователь с данным CN подключаться.

    Пользователь может подключаться если у него есть хотя бы один
    неотозванный и неистекший сертификат.
    """
    active_account = db.query(Account).filter(
        Account.cn == cn,
        Account.is_revoked == False,
        or_(
            Account.valid_to == None,
            Account.valid_to >= datetime.utcnow()
        )
    ).first()
    return active_account is not None


def _get_account_certificates(db: Session, cn: str) -> List[Account]:
    """Возвращает все сертификаты пользователя с данным CN."""
    return db.query(Account).filter(Account.cn == cn).all()


@router.get(
    "/accounts",
    response_model=AccountListResponse,
    responses={401: {"model": ErrorResponse}}
)
def list_accounts(
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Элементов на страницу"),
    is_revoked: Optional[bool] = Query(None, description="Фильтр по наличию отозванных сертификатов"),
    has_ccd: Optional[bool] = Query(None, description="Фильтр по наличию CCD"),
    search: Optional[str] = Query(None, description="Поиск по CN"),
    sort_by: str = Query("cn", description="Поле для сортировки: cn, created_at, cert_count, active_certs"),
    sort_order: str = Query("asc", description="Направление сортировки: asc, desc"),
    db: Session = Depends(get_db)
):
    """
    Список аккаунтов с пагинацией и фильтрами.

    Группирует результаты по CN, показывая агрегированные данные:
    - Общее количество сертификатов
    - Количество активных сертификатов
    - Статус "активен" если есть хоть один неотозванный

    I7.1: Только SELECT запросы
    I7.3: Пагинация через page/per_page
    I7.4: Фильтры is_revoked, has_ccd, search
    """
    # I7.1: Только SELECT запросы
    # Группировка по CN с агрегацией данных
    query = db.query(
        Account.cn,
        func.count(Account.id).label('cert_count'),
        func.sum(case((and_(
            Account.is_revoked == False,
            or_(
                Account.valid_to == None,
                Account.valid_to >= datetime.utcnow()
            )
        ), 1), else_=0)).label('active_certs'),
        func.max(Account.has_ccd).label('has_ccd'),
        func.min(Account.created_at).label('created_at')
    ).group_by(Account.cn)

    # I7.4: Применяем фильтры
    if has_ccd is not None:
        query = query.having(func.max(Account.has_ccd) == has_ccd)
    if is_revoked is not None:
        # is_revoked=True  -> у пользователя есть хотя бы один отозванный сертификат
        # is_revoked=False -> ни одного отозванного сертификата
        if is_revoked:
            query = query.having(func.max(Account.is_revoked) == True)
        else:
            query = query.having(func.max(Account.is_revoked) == False)
    if search:
        query = query.filter(Account.cn.ilike(f"%{search}%"))

    # Применяем сортировку ДО пагинации (ключевой момент!)
    # Используем агрегированные поля для сортировки
    sort_column_map = {
        "cn": Account.cn,
        "created_at": func.min(Account.created_at),
        "cert_count": func.count(Account.id),
        "active_certs": func.sum(case((and_(
            Account.is_revoked == False,
            or_(
                Account.valid_to == None,
                Account.valid_to >= datetime.utcnow()
            )
        ), 1), else_=0))
    }
    
    # Валидация параметра сортировки
    sort_column = sort_column_map.get(sort_by, Account.cn)
    
    # Применяем направление сортировки
    if sort_order.lower() == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(asc(sort_column))

    # I7.3: Пагинация
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    total_pages = (total + per_page - 1) // per_page

    # Формируем ответ с агрегированными данными
    data = []
    for item in items:
        active_certs = int(item.active_certs or 0)
        data.append({
            "cn": item.cn,
            "cert_count": item.cert_count,
            "active_certs": active_certs,
            "has_active_cert": active_certs > 0,
            "has_ccd": bool(item.has_ccd),
            "created_at": item.created_at
        })

    return {
        "data": data,
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "sort_by": sort_by,
            "sort_order": sort_order
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

    Возвращает список всех сертификатов пользователя с данным CN
    и агрегированную информацию.

    I7.5: При отсутствии данных возвращается 404
    """
    # I7.1: Только SELECT запросы
    # Получаем все сертификаты пользователя
    accounts = _get_account_certificates(db, cn)

    # I7.5: 404 если аккаунт не найден
    if not accounts:
        raise HTTPException(
            status_code=404,
            detail={"error": "Account not found", "code": "ACCOUNT_NOT_FOUND"}
        )

    # Формируем список сертификатов
    certificates = []
    for account in accounts:
        certificates.append({
            "id": account.id,
            "serial_number": account.serial_number,
            "valid_from": account.valid_from,
            "valid_to": account.valid_to,
            "is_revoked": account.is_revoked,
            "revoked_at": account.revoked_at
        })

    # Считаем статистику
    active_certs = sum(1 for a in accounts if not a.is_revoked and (
        not a.valid_to or a.valid_to >= datetime.utcnow()
    ))
    has_ccd = any(a.has_ccd for a in accounts)

    # Получаем последнюю сессию по любому из account_id
    account_ids = [a.id for a in accounts]
    last_session = None
    latest_session = db.query(SessionModel).filter(
        SessionModel.account_id.in_(account_ids)
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
        "cn": cn,
        "certificates": certificates,
        "cert_count": len(accounts),
        "active_certs": active_certs,
        "can_connect": _can_user_connect(db, cn),
        "has_ccd": has_ccd,
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

    Возвращает сессии для всех сертификатов пользователя с данным CN.

    I7.4: Фильтры from, to, status
    I7.5: 404 если аккаунт не найден
    """
    # I7.1: Только SELECT запросы
    # Сначала находим все аккаунты пользователя
    accounts = _get_account_certificates(db, cn)

    # I7.5: 404 если аккаунт не найден
    if not accounts:
        raise HTTPException(
            status_code=404,
            detail={"error": "Account not found", "code": "ACCOUNT_NOT_FOUND"}
        )

    # Получаем сессии для всех account_id пользователя
    account_ids = [a.id for a in accounts]
    query = db.query(SessionModel).filter(SessionModel.account_id.in_(account_ids))

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
