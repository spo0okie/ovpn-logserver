"""
Несколько пользователей web/API: у каждого свой пароль, вход по Basic Auth и
через форму, сессия убранного из конфига пользователя перестаёт действовать.
"""

import base64

import bcrypt
import pytest

from web import auth


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


USERS = [
    {"username": "admin", "password": None, "password_hash": _hash("admin_pw")},
    {"username": "arms", "password": None, "password_hash": _hash("arms_pw")},
    {"username": "auditor", "password": "legacy_pw", "password_hash": None},
]


@pytest.fixture
def users(mocker):
    current = list(USERS)
    mocker.patch.object(auth, "get_web_users", side_effect=lambda: current)
    return current


class TestMultipleUsers:

    @pytest.mark.parametrize("user,password", [
        ("admin", "admin_pw"), ("arms", "arms_pw"), ("auditor", "legacy_pw"),
    ])
    def test_each_user_logs_in_with_own_password(self, client, users, user, password):
        resp = client.get("/api/v1/servers", headers=_basic(user, password))
        assert resp.status_code == 200

    @pytest.mark.parametrize("user,password", [
        ("arms", "admin_pw"),     # чужой пароль
        ("admin", "arms_pw"),
        ("ARMS", "arms_pw"),      # логин регистрозависимый
        ("nobody", "arms_pw"),
    ])
    def test_wrong_pairs_rejected(self, client, users, user, password):
        resp = client.get("/api/v1/servers", headers=_basic(user, password))
        assert resp.status_code == 401

    def test_non_ascii_username_rejected_not_raised(self, client, users):
        resp = client.get("/api/v1/servers", headers=_basic("пользователь", "x"))
        assert resp.status_code == 401

    def test_form_login_second_user(self, client, users):
        resp = client.post("/login", data={"username": "arms", "password": "arms_pw"},
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "session_id" in resp.cookies

    def test_session_of_removed_user_is_rejected(self, client, users):
        resp = client.post("/login", data={"username": "arms", "password": "arms_pw"},
                           follow_redirects=False)
        client.cookies.set("session_id", resp.cookies["session_id"])
        assert client.get("/api/v1/servers").status_code == 200

        users[:] = [u for u in users if u["username"] != "arms"]
        assert client.get("/api/v1/servers").status_code == 401
