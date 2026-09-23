"""
Вход по bcrypt-хешу (password_hash) — рекомендованный способ хранения пароля.

Раньше проверка шла через passlib 1.7.4, несовместимый с bcrypt>=4.1: verify()
падал с ValueError на любом пароле, auth.py превращал это в False, и вход по
password_hash не работал вовсе. Тесты этого не видели — conftest использует
plaintext WEB_AUTH_PASSWORD. Здесь путь с хешем проверяется явно, в том числе
через настоящий HTTP Basic Auth.
"""

import base64

import bcrypt
import pytest

from web import auth


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


class TestVerifyPasswordHash:

    def test_correct_password_accepted(self):
        assert auth._verify_password("s3cret", _hash("s3cret"), None) is True

    def test_wrong_password_rejected(self):
        assert auth._verify_password("wrong", _hash("s3cret"), None) is False

    def test_hash_has_priority_over_plaintext(self):
        """Если заданы оба, решает хеш: plaintext-совпадение не пускает."""
        assert auth._verify_password("plain", _hash("s3cret"), "plain") is False

    def test_non_ascii_password(self):
        assert auth._verify_password("пароль-№1", _hash("пароль-№1"), None) is True

    def test_malformed_hash_rejected_not_raised(self):
        assert auth._verify_password("s3cret", "not-a-bcrypt-hash", None) is False

    def test_password_over_72_bytes_rejected_not_raised(self):
        """bcrypt 5.x бросает ValueError на пароль > 72 байт — это отказ, не 500."""
        assert auth._verify_password("x" * 100, _hash("s3cret"), None) is False


class TestBasicAuthWithHash:

    @pytest.fixture
    def hashed_credentials(self, mocker):
        mocker.patch.object(
            auth, "get_web_auth_credentials",
            return_value={"username": "admin", "password": None,
                          "password_hash": _hash("hashed_pw")},
        )

    def _basic(self, user, password):
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_basic_auth_with_hash_succeeds(self, client, hashed_credentials):
        resp = client.get("/api/v1/servers", headers=self._basic("admin", "hashed_pw"))
        assert resp.status_code == 200

    def test_basic_auth_with_hash_wrong_password(self, client, hashed_credentials):
        resp = client.get("/api/v1/servers", headers=self._basic("admin", "nope"))
        assert resp.status_code == 401
