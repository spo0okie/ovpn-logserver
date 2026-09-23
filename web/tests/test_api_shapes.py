"""Проверка задокументированных в docs/api.md форматов ответов (по факту)."""
import base64


def _auth():
    return {"Authorization": "Basic " + base64.b64encode(b"admin:admin_password_123").decode()}


def test_401_is_string_detail(client):
    r = client.get("/api/v1/sessions")
    assert r.status_code == 401
    assert isinstance(r.json()["detail"], str)


def test_422_is_fastapi_list(client):
    r = client.get("/api/v1/sessions?per_page=1000", headers=_auth())
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_400_is_object_with_code(client):
    r = client.get("/api/v1/accounts?sort_by=nope", headers=_auth())
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAMETER"


def test_sort_by_has_ccd_accepted(client):
    assert client.get("/api/v1/accounts?sort_by=has_ccd", headers=_auth()).status_code == 200


def test_connections_requires_dates(client):
    assert client.get("/api/v1/stats/connections", headers=_auth()).status_code == 422


def test_active_sessions_shape(client):
    body = client.get("/api/v1/sessions/active", headers=_auth()).json()
    assert set(body) == {"count", "data"}
