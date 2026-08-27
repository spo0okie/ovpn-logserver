"""
Тесты мультисайт-скоупинга хуков client_connect/client_disconnect.

Проверяют:
- сессия при подключении получает server_id своего инстанса (по openvpn.server_name);
- C5.1-C5.4 скоупятся по серверу: reconnect на одном сайте не закрывает живую
  сессию того же CN на другом;
- disconnect закрывает сессию только своего сервера.
"""

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.time import utcnow
from core.database import Base
from core.models import Account, Session, VpnServer
from collector.client_connect import client_connect
from collector.client_disconnect import client_disconnect
from collector.server_registry import resolve_server_id


@pytest.fixture(scope="function")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    from core import models  # noqa: F401
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def make_db(test_engine):
    TestSession = sessionmaker(bind=test_engine)
    sessions = []

    def _make():
        db = TestSession()
        sessions.append(db)
        return db

    yield _make
    for db in sessions:
        db.close()


@pytest.fixture
def mock_geoip(mocker):
    return mocker.patch(
        'collector.client_connect.resolve_geoip',
        return_value={'country': 'TestCountry', 'city': 'TestCity'},
    )


CONNECT_ENV = {
    'common_name': 'roaming_user',
    'trusted_ip': '203.0.113.10',
    'tls_serial_0': '123456',
}

DISCONNECT_ENV = {
    'common_name': 'roaming_user',
    'bytes_sent': '100',
    'bytes_received': '200',
}


def _run_hook(hook, env_vars, db):
    """Запускает хук с подменой OpenVPN-переменных окружения."""
    old_environ = dict(os.environ)
    for key in (
        'common_name', 'trusted_ip', 'trusted_port', 'tls_serial_0',
        'ifconfig_pool_remote_ip', 'time_unix', 'bytes_sent', 'bytes_received',
        'time_duration',
    ):
        os.environ.pop(key, None)
    os.environ.update(env_vars)
    try:
        return hook(db_session=db)
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


class TestConnectServerScope:

    def test_connect_sets_server_id(self, make_db, mock_geoip, mocker):
        """Созданная сессия несёт server_id инстанса из конфигурации."""
        mocker.patch('collector.client_connect.SERVER_NAME', 'site-a')
        db = make_db()

        assert _run_hook(client_connect, CONNECT_ENV, db) == 0

        check = make_db()
        server = check.query(VpnServer).filter_by(name='site-a').one()
        session = check.query(Session).one()
        assert session.server_id == server.id

    def test_reconnect_does_not_close_other_site_session(self, make_db, mock_geoip, mocker):
        """C5 скоупится по серверу: живая сессия на другом сайте не orphaned."""
        db = make_db()
        sid_b = resolve_server_id(db, 'site-b')
        account = Account(cn='roaming_user', serial_number='123456')
        db.add(account)
        db.commit()
        foreign = Session(
            account_id=account.id,
            server_id=sid_b,
            connected_at=utcnow(),
            source_ip='198.51.100.1',
            status='active',
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id

        mocker.patch('collector.client_connect.SERVER_NAME', 'site-a')
        assert _run_hook(client_connect, CONNECT_ENV, make_db()) == 0

        check = make_db()
        assert check.get(Session, foreign_id).status == 'active'
        # новая сессия создана на site-a
        sid_a = check.query(VpnServer).filter_by(name='site-a').one().id
        assert check.query(Session).filter_by(server_id=sid_a, status='active').count() == 1

    def test_reconnect_closes_own_site_session(self, make_db, mock_geoip, mocker):
        """C5.1 в пределах своего сервера продолжает работать."""
        db = make_db()
        sid_a = resolve_server_id(db, 'site-a')
        account = Account(cn='roaming_user', serial_number='123456')
        db.add(account)
        db.commit()
        own_old = Session(
            account_id=account.id,
            server_id=sid_a,
            connected_at=utcnow(),
            source_ip='198.51.100.1',
            status='active',
        )
        db.add(own_old)
        db.commit()
        own_old_id = own_old.id

        mocker.patch('collector.client_connect.SERVER_NAME', 'site-a')
        assert _run_hook(client_connect, CONNECT_ENV, make_db()) == 0

        check = make_db()
        assert check.get(Session, own_old_id).status == 'error'
        assert check.query(Session).filter_by(status='active').count() == 1


class TestDisconnectServerScope:

    def test_disconnect_closes_only_own_site_session(self, make_db, mocker):
        """Отключение на site-a не закрывает сессию того же CN на site-b."""
        db = make_db()
        sid_a = resolve_server_id(db, 'site-a')
        sid_b = resolve_server_id(db, 'site-b')
        account = Account(cn='roaming_user', serial_number='123456')
        db.add(account)
        db.commit()
        own = Session(
            account_id=account.id, server_id=sid_a,
            connected_at=utcnow(), source_ip='1.1.1.1', status='active',
        )
        foreign = Session(
            account_id=account.id, server_id=sid_b,
            connected_at=utcnow(), source_ip='2.2.2.2', status='active',
        )
        db.add_all([own, foreign])
        db.commit()
        own_id, foreign_id = own.id, foreign.id

        mocker.patch('collector.client_disconnect.SERVER_NAME', 'site-a')
        assert _run_hook(client_disconnect, DISCONNECT_ENV, make_db()) == 0

        check = make_db()
        assert check.get(Session, own_id).status == 'closed'
        assert check.get(Session, foreign_id).status == 'active'

    def test_disconnect_unknown_server_falls_back_unscoped(self, make_db, mocker):
        """Сервер не зарегистрирован (create=False) — поведение как раньше."""
        db = make_db()
        account = Account(cn='roaming_user', serial_number='123456')
        db.add(account)
        db.commit()
        legacy = Session(
            account_id=account.id, server_id=None,
            connected_at=utcnow(), source_ip='1.1.1.1', status='active',
        )
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id

        mocker.patch('collector.client_disconnect.SERVER_NAME', 'never-connected')
        assert _run_hook(client_disconnect, DISCONNECT_ENV, make_db()) == 0

        check = make_db()
        assert check.get(Session, legacy_id).status == 'closed'
        # disconnect ничего не создаёт (I5.6): сервер так и не зарегистрирован
        assert check.query(VpnServer).filter_by(name='never-connected').count() == 0
