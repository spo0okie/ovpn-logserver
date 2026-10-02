"""
API для внешних интеграций (инвентаризация ARMS, integrations/arms/).

Батч-статус пар «CN + инстанс»: внешняя система рисует статус VPN у каждого
IP-адреса страницы (иконки, колонки гридов), и по запросу на адрес это
были бы сотни обращений на одну страницу. Здесь — один запрос на страницу
и фиксированное число SELECT'ов на весь батч.

I7.1: Только SELECT запросы (POST — только ради тела со списком пар)
I7.6: Аутентификация обязательна (через Depends в main.py)
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.models import Account, CcdStatus, Session as SessionModel, VpnServer
from core.time import utcnow
from web.dependencies import get_db
from web.schemas import (
    ErrorResponse,
    IntegrationStatusItem,
    IntegrationStatusRequest,
    IntegrationStatusResponse,
)

router = APIRouter(tags=["integrations"])


def _key(cn: str) -> str:
    """
    Ключ сопоставления CN. В MySQL collation регистронезависимая, а внешняя
    система может хранить CN в другом регистре — сравниваем так же, как БД,
    и одинаково на SQLite (тесты) и MySQL (прод).
    """
    return cn.strip().lower()


def _session_dict(session: SessionModel, server_name: Optional[str]) -> dict:
    return {
        "id": session.id,
        "server_name": server_name,
        "status": session.status,
        "connected_at": session.connected_at,
        "disconnected_at": session.disconnected_at,
        "source_ip": session.source_ip,
        "virtual_ip": session.virtual_ip,
        "country": session.country,
        "city": session.city,
    }


def _state(certs: List[Account], has_ccd: bool, active: Optional[dict]) -> str:
    """
    Статус пары по убыванию приоритета: online -> enabled -> disabled ->
    revoked. Онлайн важнее всего: живая сессия — факт, даже если сертификат
    успели отозвать (CRL ещё не доехал до сервера).
    """
    if active:
        return "online"
    now = utcnow()
    valid = any(
        not c.is_revoked and (c.valid_to is None or c.valid_to >= now)
        for c in certs
    )
    if not valid:
        return "revoked"
    return "enabled" if has_ccd else "disabled"


def _certs_summary(certs: List[Account]) -> dict:
    now = utcnow()
    revoked = [c for c in certs if c.is_revoked]
    expired = [c for c in certs if not c.is_revoked and c.valid_to is not None and c.valid_to < now]
    valid = [c for c in certs if c not in revoked and c not in expired]
    valid_to = [c.valid_to for c in valid if c.valid_to is not None]
    return {
        "total": len(certs),
        "active": len(valid),
        "revoked": len(revoked),
        "expired": len(expired),
        # срок самого долгоживущего действующего сертификата: «когда
        # пользователь перестанет подключаться, если ничего не делать»
        "valid_to": max(valid_to) if valid_to else None,
    }


@router.post(
    "/integrations/status",
    response_model=IntegrationStatusResponse,
    responses={401: {"model": ErrorResponse}},
)
def integration_status(
    request: IntegrationStatusRequest,
    db: Session = Depends(get_db),
):
    """
    Статус VPN для списка пар «CN + инстанс».

    `server` — имя инстанса (`vpn_servers.name`); `null` — любой инстанс
    (CCD хотя бы на одном, сессии на всех). Legacy-сессии (`server_id IS
    NULL`) к конкретному инстансу не относятся и видны только при
    `server: null` — иначе на мультисайте чужие старые сессии выдавались бы
    за сессии инстанса.

    Ответ — в порядке запроса, по элементу на пару.
    """
    items = request.items
    keys = sorted({_key(i.cn) for i in items if i.cn.strip()})
    if not keys:
        return {"data": [
            {"cn": i.cn, "server": i.server, "state": "not_found"} for i in items
        ]}

    # сертификаты
    certs: Dict[str, List[Account]] = defaultdict(list)
    for account in db.query(Account).filter(func.lower(Account.cn).in_(keys)).all():
        certs[_key(account.cn)].append(account)

    account_key = {a.id: k for k, lst in certs.items() for a in lst}
    account_ids = list(account_key)

    # CCD по серверам: {cn_key: {server_name}}
    ccd: Dict[str, set] = defaultdict(set)
    for cn, server_name in (
        db.query(CcdStatus.cn, VpnServer.name)
        .join(VpnServer, CcdStatus.server_id == VpnServer.id)
        .filter(func.lower(CcdStatus.cn).in_(keys))
        .all()
    ):
        ccd[_key(cn)].add(server_name)

    # активные сессии, новые первыми: [(cn_key, server_name, session)]
    active: List[Tuple[str, Optional[str], SessionModel]] = []
    # последняя сессия на (cn_key, server_name) — одним group by
    last: Dict[Tuple[str, Optional[str]], Tuple[SessionModel, Optional[str]]] = {}
    if account_ids:
        for session, server_name in (
            db.query(SessionModel, VpnServer.name)
            .outerjoin(VpnServer, SessionModel.server_id == VpnServer.id)
            .filter(SessionModel.account_id.in_(account_ids), SessionModel.status == "active")
            .order_by(SessionModel.connected_at.desc())
            .all()
        ):
            active.append((account_key[session.account_id], server_name, session))

        latest = (
            db.query(
                SessionModel.account_id,
                SessionModel.server_id,
                func.max(SessionModel.connected_at).label("connected_at"),
            )
            .filter(SessionModel.account_id.in_(account_ids))
            .group_by(SessionModel.account_id, SessionModel.server_id)
            .subquery()
        )
        rows = (
            db.query(SessionModel, VpnServer.name)
            .join(latest, (SessionModel.account_id == latest.c.account_id)
                  & (SessionModel.connected_at == latest.c.connected_at)
                  & or_(SessionModel.server_id == latest.c.server_id,
                        (SessionModel.server_id.is_(None)) & (latest.c.server_id.is_(None))))
            .outerjoin(VpnServer, SessionModel.server_id == VpnServer.id)
            .all()
        )
        for session, server_name in rows:
            k = (account_key[session.account_id], server_name)
            if k not in last or session.connected_at > last[k][0].connected_at:
                last[k] = (session, server_name)

    data = []
    for item in items:
        k = _key(item.cn)
        own = certs.get(k, [])
        if not own:
            data.append({"cn": item.cn, "server": item.server, "state": "not_found"})
            continue

        def on_server(server_name: Optional[str]) -> bool:
            return item.server is None or server_name == item.server

        active_session = next(
            (_session_dict(s, srv) for key, srv, s in active if key == k and on_server(srv)),
            None,
        )
        candidates = [v for (key, srv), v in last.items() if key == k and on_server(srv)]
        last_session = None
        if candidates:
            s, srv = max(candidates, key=lambda v: v[0].connected_at)
            last_session = _session_dict(s, srv)

        has_ccd = bool(ccd.get(k)) if item.server is None else item.server in ccd.get(k, set())

        data.append({
            "cn": item.cn,
            "server": item.server,
            "state": _state(own, has_ccd, active_session),
            "has_ccd": has_ccd,
            "certificates": _certs_summary(own),
            "active_session": active_session,
            "last_session": last_session,
        })

    return {"data": data}
