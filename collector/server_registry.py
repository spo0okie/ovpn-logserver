"""
Регистрация и поиск инстанса OpenVPN-сервера в справочнике vpn_servers.

Мультисайт (docs/multisite.md): каждый инстанс OpenVPN идентифицируется именем
из конфигурации (openvpn.server_name / ENV OPENVPN_SERVER_NAME). Запись в
vpn_servers создаётся автоматически при первом событии от инстанса — заводить
её руками не нужно.

Используется хуками client_connect/client_disconnect и sync-задачами
(ccd_checker, session_cleanup) для скоупинга данных по серверу.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.time import utcnow  # noqa: E402
from core.models import VpnServer  # noqa: E402

logger = logging.getLogger(__name__)


def resolve_server_id(db, name: str, create: bool = True):
    """
    Возвращает id сервера по имени; при create=True создаёт запись при отсутствии.

    Для MySQL создание идёт через INSERT ... ON DUPLICATE KEY UPDATE — тот же
    паттерн, что и для accounts в client_connect (I4.2/I4.6): без SELECT-гонки
    два одновременных хука не падают на уникальном ключе. Для SQLite (тесты) —
    select-then-insert.

    Args:
        db: сессия базы данных
        name: имя инстанса (chl, msk-2fa, ...)
        create: создавать ли запись при отсутствии

    Returns:
        int | None: id сервера; None если не найден и create=False
    """
    server = db.query(VpnServer).filter(VpnServer.name == name).first()
    if server is not None:
        return server.id
    if not create:
        return None

    now = utcnow()
    dialect_name = db.bind.dialect.name
    if dialect_name == "mysql":
        from sqlalchemy.dialects.mysql import insert
        stmt = insert(VpnServer).values(
            name=name, created_at=now, updated_at=now
        )
        stmt = stmt.on_duplicate_key_update(updated_at=now)
        db.execute(stmt)
        db.commit()
        server = db.query(VpnServer).filter(VpnServer.name == name).first()
    else:
        server = VpnServer(name=name, created_at=now, updated_at=now)
        db.add(server)
        db.commit()

    logger.info("VPN server registered: id=%s, name='%s'", server.id, name)
    return server.id
