"""
API endpoints для работы с неудачными попытками подключения.

I7.1: Только SELECT запросы к БД
I7.2: Ответы соответствуют формату из api-design.md
I7.3: Пагинация работает корректно
I7.4: Фильтры работают как указано в спецификации
I7.5: При отсутствии данных возвращается пустой список
I7.6: Аутентификация обязательна (через Depends в main.py)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.models import Account, ConnectionAttempt
from web.dependencies import get_db
from web.schemas import (
    AttemptListResponse,
    PaginationMeta,
    ErrorResponse
)

router = APIRouter(tags=["attempts"])


def _attempt_to_list_item(attempt: ConnectionAttempt) -> dict:
    """Преобразует модель ConnectionAttempt в словарь для списка."""
    # Извлекаем префикс из CN если есть
    prefix = None
    cn = None
    if attempt.account:
        cn = attempt.account.cn
        if "_" in cn:
            prefix = cn.split("_")[0] + "_"
    elif attempt.cert_cn:
        cn = attempt.cert_cn
        if "_" in cn:
            prefix = cn.split("_")[0] + "_"

    return {
        "id": attempt.id,
        "account": {
            "cn": cn,
            "prefix": prefix
        },
        "attempted_at": attempt.attempted_at,
        "source_ip": attempt.source_ip,
        "cert_cn": attempt.cert_cn,
        "failure_reason": attempt.failure_reason,
        "failure_type": attempt.failure_type,
        "details": attempt.details
    }


@router.get(
    "/attempts",
    response_model=AttemptListResponse,
    responses={401: {"model": ErrorResponse}}
)
def list_attempts(
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Элементов на страницу"),
    account: Optional[str] = Query(None, description="Фильтр по CN"),
    from_date: Optional[datetime] = Query(None, alias="from", description="Начало периода"),
    to_date: Optional[datetime] = Query(None, alias="to", description="Конец периода"),
    failure_type: Optional[str] = Query(None, description="Тип ошибки"),
    source_ip: Optional[str] = Query(None, description="Фильтр по IP"),
    db: Session = Depends(get_db)
):
    """
    Список неудачных попыток подключения.

    I7.1: Только SELECT запросы
    I7.3: Пагинация через page/per_page
    I7.4: Фильтры account, from, to, failure_type, source_ip
    I7.5: При отсутствии данных возвращается пустой список
    """
    # I7.1: Только SELECT запросы
    query = db.query(ConnectionAttempt).outerjoin(
        Account, ConnectionAttempt.account_id == Account.id
    )

    # I7.4: Применяем фильтры
    if account:
        query = query.filter(
            (Account.cn == account) | (ConnectionAttempt.cert_cn == account)
        )
    if from_date:
        query = query.filter(ConnectionAttempt.attempted_at >= from_date)
    if to_date:
        query = query.filter(ConnectionAttempt.attempted_at <= to_date)
    if failure_type:
        query = query.filter(ConnectionAttempt.failure_type == failure_type)
    if source_ip:
        query = query.filter(ConnectionAttempt.source_ip == source_ip)

    query = query.order_by(ConnectionAttempt.attempted_at.desc())

    # I7.3: Пагинация
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    total_pages = (total + per_page - 1) // per_page

    # I7.5: При отсутствии данных возвращается пустой список (не 404)
    return {
        "data": [_attempt_to_list_item(a) for a in items],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages
        }
    }
