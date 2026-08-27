"""
API endpoints для справочника OpenVPN-серверов (мультисайт).

I7.1: Только SELECT запросы к БД
I7.6: Аутентификация обязательна (через Depends в main.py)

Записи в vpn_servers создаёт collector автоматически — здесь только чтение
(наполнение фильтров UI и внешняя автоматизация).
"""

from fastapi import APIRouter, Depends

from core.models import VpnServer
from web.dependencies import get_db
from web.schemas import ServersResponse, ErrorResponse

from sqlalchemy.orm import Session

router = APIRouter(tags=["servers"])


@router.get(
    "/servers",
    response_model=ServersResponse,
    responses={401: {"model": ErrorResponse}}
)
def list_servers(db: Session = Depends(get_db)):
    """Список зарегистрированных инстансов OpenVPN."""
    servers = db.query(VpnServer).order_by(VpnServer.name).all()
    return {
        "data": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "created_at": s.created_at,
            }
            for s in servers
        ]
    }
