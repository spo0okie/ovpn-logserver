"""
Тесты мультисайт-возможностей API/UI:
- /api/v1/servers — справочник инстансов;
- фильтр sessions по серверу и server_name в ответах;
- per-site статус CCD в деталях аккаунта.
"""

from datetime import timedelta

import pytest

from core.time import utcnow
from core.models import Account, CcdStatus, Session as SessionModel, VpnServer


@pytest.fixture
def two_servers(db):
    a = VpnServer(name="site-a")
    b = VpnServer(name="site-b")
    db.add_all([a, b])
    db.commit()
    db.refresh(a)
    db.refresh(b)
    return a, b


@pytest.fixture
def sessions_on_servers(db, sample_account, two_servers):
    a, b = two_servers
    s_a = SessionModel(
        account_id=sample_account.id, server_id=a.id,
        connected_at=utcnow() - timedelta(hours=2),
        source_ip="10.0.0.1", status="active",
    )
    s_b = SessionModel(
        account_id=sample_account.id, server_id=b.id,
        connected_at=utcnow() - timedelta(hours=1),
        source_ip="10.0.0.2", status="active",
    )
    s_legacy = SessionModel(
        account_id=sample_account.id, server_id=None,
        connected_at=utcnow() - timedelta(days=1),
        disconnected_at=utcnow() - timedelta(hours=23),
        source_ip="10.0.0.3", status="closed",
    )
    db.add_all([s_a, s_b, s_legacy])
    db.commit()
    return s_a, s_b, s_legacy


class TestServersEndpoint:

    def test_list_servers(self, client, auth_headers, two_servers):
        resp = client.get("/api/v1/servers", headers=auth_headers)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["data"]]
        assert names == ["site-a", "site-b"]

    def test_requires_auth(self, client, two_servers):
        assert client.get("/api/v1/servers").status_code == 401


class TestSessionsServerFilter:

    def test_filter_by_server(self, client, auth_headers, sessions_on_servers):
        resp = client.get("/api/v1/sessions?server=site-a", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["server_name"] == "site-a"

    def test_no_filter_includes_legacy(self, client, auth_headers, sessions_on_servers):
        resp = client.get("/api/v1/sessions", headers=auth_headers)
        data = resp.json()["data"]
        assert len(data) == 3
        # legacy-сессия отдается с server_name=None
        assert any(item["server_name"] is None for item in data)

    def test_session_detail_has_server(self, client, auth_headers, sessions_on_servers):
        s_a = sessions_on_servers[0]
        resp = client.get(f"/api/v1/sessions/{s_a.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["server_name"] == "site-a"

    def test_active_sessions_have_server(self, client, auth_headers, sessions_on_servers):
        resp = client.get("/api/v1/sessions/active", headers=auth_headers)
        assert resp.status_code == 200
        names = {item["server_name"] for item in resp.json()["data"]}
        assert names == {"site-a", "site-b"}


class TestAccountCcdSites:

    def test_account_detail_ccd_sites(self, client, auth_headers, db, sample_account, two_servers):
        a, b = two_servers
        # CCD-файл есть только на site-a
        db.add(CcdStatus(cn=sample_account.cn, server_id=a.id,
                         ccd_updated_at=utcnow()))
        db.commit()

        resp = client.get(f"/api/v1/accounts/{sample_account.cn}", headers=auth_headers)
        assert resp.status_code == 200
        sites = resp.json()["ccd_sites"]
        assert [s["server_name"] for s in sites] == ["site-a"]

    def test_account_detail_no_ccd_sites(self, client, auth_headers, sample_account):
        resp = client.get(f"/api/v1/accounts/{sample_account.cn}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ccd_sites"] == []
