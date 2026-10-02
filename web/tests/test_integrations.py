"""
Тесты батч-статуса для внешних интеграций (POST /api/v1/integrations/status):
приоритет статусов, скоуп по инстансу, текущая и последняя сессия,
регистронезависимое сопоставление CN, порядок ответа.
"""

from datetime import timedelta

import pytest

from core.time import utcnow
from core.models import Account, CcdStatus, Session as SessionModel, VpnServer

URL = "/api/v1/integrations/status"


def _account(db, cn, revoked=False, valid_to_days=365):
    account = Account(
        cn=cn,
        serial_number=f"{cn}-{revoked}-{valid_to_days}",
        valid_from=utcnow() - timedelta(days=30),
        valid_to=utcnow() + timedelta(days=valid_to_days),
        is_revoked=revoked,
        revoked_at=utcnow() - timedelta(days=1) if revoked else None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _session(db, account, server, hours_ago, status="closed", source_ip="203.0.113.5"):
    connected = utcnow() - timedelta(hours=hours_ago)
    session = SessionModel(
        account_id=account.id,
        server_id=server.id if server else None,
        connected_at=connected,
        disconnected_at=None if status == "active" else connected + timedelta(minutes=30),
        source_ip=source_ip,
        virtual_ip="10.8.0.10",
        country="Russia",
        city="Chelyabinsk",
        status=status,
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def servers(db):
    local = VpnServer(name="local")
    twofa = VpnServer(name="local-2fa")
    db.add_all([local, twofa])
    db.commit()
    db.refresh(local)
    db.refresh(twofa)
    return local, twofa


def _status(client, auth_headers, items):
    resp = client.post(URL, json={"items": items}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class TestIntegrationStatus:

    def test_requires_auth(self, client):
        assert client.post(URL, json={"items": []}).status_code == 401

    def test_not_found(self, client, auth_headers, servers):
        data = _status(client, auth_headers, [{"cn": "ghost", "server": "local"}])
        assert data == [{
            "cn": "ghost", "server": "local", "state": "not_found", "has_ccd": False,
            "certificates": None, "active_session": None, "last_session": None,
        }]

    def test_state_priority(self, client, auth_headers, db, servers):
        local, _ = servers
        # enabled: действующий сертификат + CCD на инстансе
        _account(db, "enabled_user")
        db.add(CcdStatus(cn="enabled_user", server_id=local.id))
        # disabled: действующий сертификат, CCD нет
        _account(db, "disabled_user")
        # revoked: действующих нет (отозван + истёк)
        _account(db, "revoked_user", revoked=True)
        _account(db, "revoked_user", valid_to_days=-1)
        # online: живая сессия важнее отозванного сертификата
        online = _account(db, "online_user", revoked=True)
        db.commit()
        _session(db, online, local, 1, status="active")

        data = _status(client, auth_headers, [
            {"cn": cn, "server": "local"}
            for cn in ("enabled_user", "disabled_user", "revoked_user", "online_user")
        ])
        assert [d["state"] for d in data] == ["enabled", "disabled", "revoked", "online"]

        revoked = data[2]["certificates"]
        assert (revoked["total"], revoked["active"], revoked["revoked"], revoked["expired"]) == (2, 0, 1, 1)
        assert revoked["valid_to"] is None

    def test_scoped_by_server(self, client, auth_headers, db, servers):
        """CCD и сессии другого инстанса не делают пару online/enabled."""
        local, twofa = servers
        account = _account(db, "ivanov")
        db.add(CcdStatus(cn="ivanov", server_id=twofa.id))
        db.commit()
        _session(db, account, twofa, 1, status="active")

        on_local, on_twofa, anywhere = _status(client, auth_headers, [
            {"cn": "ivanov", "server": "local"},
            {"cn": "ivanov", "server": "local-2fa"},
            {"cn": "ivanov", "server": None},
        ])
        assert on_local["state"] == "disabled"
        assert on_local["active_session"] is None and on_local["last_session"] is None
        assert on_twofa["state"] == "online"
        assert on_twofa["active_session"]["server_name"] == "local-2fa"
        assert anywhere["state"] == "online"

    def test_last_session_for_offline(self, client, auth_headers, db, servers):
        local, twofa = servers
        account = _account(db, "petrov")
        _session(db, account, local, 48, source_ip="198.51.100.1")
        _session(db, account, local, 5, source_ip="198.51.100.2")
        _session(db, account, twofa, 1, source_ip="198.51.100.3")
        _session(db, account, None, 0.5, source_ip="198.51.100.4")  # legacy

        on_local, anywhere = _status(client, auth_headers, [
            {"cn": "petrov", "server": "local"},
            {"cn": "petrov"},
        ])
        assert on_local["active_session"] is None
        assert on_local["last_session"]["source_ip"] == "198.51.100.2"
        assert on_local["last_session"]["country"] == "Russia"
        # legacy-сессия видна только без скоупа по инстансу
        assert anywhere["last_session"]["source_ip"] == "198.51.100.4"
        assert anywhere["last_session"]["server_name"] is None

    def test_last_session_across_certificates(self, client, auth_headers, db, servers):
        """CN перевыпущен: последняя сессия — по всем его сертификатам."""
        local, _ = servers
        old = _account(db, "sidorov", revoked=True)
        new = _account(db, "sidorov")
        _session(db, old, local, 10, source_ip="198.51.100.10")
        _session(db, new, local, 2, source_ip="198.51.100.20")

        (item,) = _status(client, auth_headers, [{"cn": "sidorov", "server": "local"}])
        assert item["last_session"]["source_ip"] == "198.51.100.20"
        assert item["certificates"]["total"] == 2

    def test_cn_case_insensitive_and_order(self, client, auth_headers, db, servers):
        _account(db, "Smirnov.A")
        data = _status(client, auth_headers, [
            {"cn": "nobody", "server": "local"},
            {"cn": "smirnov.a", "server": "local"},
        ])
        # порядок ответа = порядок запроса, CN — как спросили
        assert [d["cn"] for d in data] == ["nobody", "smirnov.a"]
        assert [d["state"] for d in data] == ["not_found", "disabled"]

    def test_empty_batch(self, client, auth_headers):
        assert _status(client, auth_headers, []) == []

    def test_batch_limit(self, client, auth_headers):
        items = [{"cn": f"u{i}"} for i in range(501)]
        resp = client.post(URL, json={"items": items}, headers=auth_headers)
        assert resp.status_code == 422
