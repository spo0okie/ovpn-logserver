"""
Тесты для проверки инвариантов этапа 7.

I7.1 - API только читает из БД (нет INSERT/UPDATE/DELETE)
I7.2 - Ответы соответствуют формату из api-design.md
I7.3 - Пагинация работает корректно
I7.4 - Фильтры работают как указано в спецификации
I7.5 - При отсутствии данных возвращается 404 или пустой список
I7.6 - Аутентификация обязательна для всех endpoints
"""

import ast
import base64
import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.models import Account, Session as SessionModel, ConnectionAttempt


# =============================================================================
# I7.1: Только чтение из БД (AST анализ)
# =============================================================================

class WriteOperationVisitor(ast.NodeVisitor):
    """AST visitor для поиска операций записи в БД."""

    def __init__(self):
        self.write_operations = []
        self.forbidden_methods = {'add', 'delete', 'commit', 'flush', 'merge', 'execute'}

    def visit_Call(self, node):
        """Проверяет вызовы методов."""
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in self.forbidden_methods:
                # Проверяем, что это вызов на объекте db (Session)
                self.write_operations.append({
                    'method': node.func.attr,
                    'line': node.lineno,
                    'col': node.col_offset
                })
        self.generic_visit(node)


def check_file_for_writes(filepath: str) -> list:
    """Проверяет файл на наличие операций записи в БД."""
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    tree = ast.parse(source)
    visitor = WriteOperationVisitor()
    visitor.visit(tree)
    return visitor.write_operations


class TestI71_ReadOnlyAPI:
    """Тест I7.1: API только читает из БД."""

    def test_accounts_no_write_operations(self):
        """Проверяет accounts.py на отсутствие операций записи."""
        writes = check_file_for_writes('web/api/accounts.py')
        assert len(writes) == 0, f"Found write operations in accounts.py: {writes}"

    def test_sessions_no_write_operations(self):
        """Проверяет sessions.py на отсутствие операций записи."""
        writes = check_file_for_writes('web/api/sessions.py')
        assert len(writes) == 0, f"Found write operations in sessions.py: {writes}"

    def test_attempts_no_write_operations(self):
        """Проверяет attempts.py на отсутствие операций записи."""
        writes = check_file_for_writes('web/api/attempts.py')
        assert len(writes) == 0, f"Found write operations in attempts.py: {writes}"

    def test_stats_no_write_operations(self):
        """Проверяет stats.py на отсутствие операций записи."""
        writes = check_file_for_writes('web/api/stats.py')
        assert len(writes) == 0, f"Found write operations in stats.py: {writes}"


# =============================================================================
# I7.6: Аутентификация обязательна
# =============================================================================

class TestI76_AuthRequired:
    """Тест I7.6: Аутентификация обязательна для всех endpoints."""

    def test_accounts_list_requires_auth(self, client: TestClient):
        """GET /accounts требует авторизации."""
        response = client.get("/api/v1/accounts")
        assert response.status_code == 401

    def test_accounts_detail_requires_auth(self, client: TestClient):
        """GET /accounts/{cn} требует авторизации."""
        response = client.get("/api/v1/accounts/test")
        assert response.status_code == 401

    def test_sessions_list_requires_auth(self, client: TestClient):
        """GET /sessions требует авторизации."""
        response = client.get("/api/v1/sessions")
        assert response.status_code == 401

    def test_sessions_active_requires_auth(self, client: TestClient):
        """GET /sessions/active требует авторизации."""
        response = client.get("/api/v1/sessions/active")
        assert response.status_code == 401

    def test_attempts_list_requires_auth(self, client: TestClient):
        """GET /attempts требует авторизации."""
        response = client.get("/api/v1/attempts")
        assert response.status_code == 401

    def test_stats_overview_requires_auth(self, client: TestClient):
        """GET /stats/overview требует авторизации."""
        response = client.get("/api/v1/stats/overview")
        assert response.status_code == 401

    def test_invalid_credentials_rejected(self, client: TestClient):
        """Неверные credentials отклоняются."""
        credentials = base64.b64encode(b"admin:wrongpassword").decode("utf-8")
        response = client.get(
            "/api/v1/accounts",
            headers={"Authorization": f"Basic {credentials}"}
        )
        assert response.status_code == 401

    def test_valid_credentials_accepted(self, client: TestClient, auth_headers: dict):
        """Верные credentials принимаются."""
        response = client.get("/api/v1/accounts", headers=auth_headers)
        assert response.status_code == 200


# =============================================================================
# I7.3: Пагинация работает корректно
# =============================================================================

class TestI73_Pagination:
    """Тест I7.3: Пагинация работает корректно."""

    def test_accounts_pagination_meta(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Проверяет наличие meta в ответе списка аккаунтов."""
        response = client.get("/api/v1/accounts?page=1&per_page=2", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "meta" in data
        assert "data" in data

        meta = data["meta"]
        assert meta["page"] == 1
        assert meta["per_page"] == 2
        assert meta["total"] == 5
        assert meta["total_pages"] == 3  # 5 элементов, 2 на страницу = 3 страницы

    def test_accounts_pagination_page_2(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Проверяет вторую страницу."""
        response = client.get("/api/v1/accounts?page=2&per_page=2", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 2
        assert data["meta"]["page"] == 2

    def test_accounts_pagination_empty_page(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Проверяет пустую страницу."""
        response = client.get("/api/v1/accounts?page=10&per_page=2", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 0
        assert data["meta"]["total"] == 5

    def test_sessions_pagination(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Проверяет пагинацию сессий."""
        response = client.get("/api/v1/sessions?page=1&per_page=1", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "meta" in data
        assert data["meta"]["page"] == 1
        assert data["meta"]["per_page"] == 1


# =============================================================================
# I7.4: Фильтры работают корректно
# =============================================================================

class TestI74_Filters:
    """Тест I7.4: Фильтры работают как указано в спецификации."""

    def test_accounts_filter_is_revoked(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Фильтр is_revoked для аккаунтов."""
        response = client.get("/api/v1/accounts?is_revoked=true", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        # 3 аккаунта с is_revoked=True (0, 2, 4)
        assert len(data["data"]) == 3
        for acc in data["data"]:
            assert acc["is_revoked"] is True

    def test_accounts_filter_has_ccd(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Фильтр has_ccd для аккаунтов."""
        response = client.get("/api/v1/accounts?has_ccd=true", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        # 2 аккаунта с has_ccd=True (1, 3)
        assert len(data["data"]) == 2
        for acc in data["data"]:
            assert acc["has_ccd"] is True

    def test_accounts_filter_search(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Фильтр search для аккаунтов."""
        response = client.get("/api/v1/accounts?search=user_1", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["cn"] == "user_1"

    def test_sessions_filter_status(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Фильтр status для сессий."""
        response = client.get("/api/v1/sessions?status=active", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["status"] == "active"

    def test_sessions_filter_account(self, client: TestClient, sample_account: Account, sample_sessions: list, auth_headers: dict):
        """Фильтр account (по CN) для сессий."""
        response = client.get(f"/api/v1/sessions?account={sample_account.cn}", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 2

    def test_attempts_filter_failure_type(self, client: TestClient, sample_attempts: list, auth_headers: dict):
        """Фильтр failure_type для попыток."""
        response = client.get("/api/v1/attempts?failure_type=cert_revoked", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["failure_type"] == "cert_revoked"


# =============================================================================
# I7.5: При отсутствии данных возвращается 404 или пустой список
# =============================================================================

class TestI75_NotFoundHandling:
    """Тест I7.5: При отсутствии данных возвращается 404 или пустой список."""

    def test_account_not_found_returns_404(self, client: TestClient, auth_headers: dict):
        """GET /accounts/{cn} возвращает 404 для несуществующего аккаунта."""
        response = client.get("/api/v1/accounts/nonexistent_user", headers=auth_headers)
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data

    def test_session_not_found_returns_404(self, client: TestClient, auth_headers: dict):
        """GET /sessions/{id} возвращает 404 для несуществующей сессии."""
        response = client.get("/api/v1/sessions/99999", headers=auth_headers)
        assert response.status_code == 404

    def test_empty_accounts_list_returns_empty(self, client: TestClient, auth_headers: dict):
        """GET /accounts возвращает пустой список если нет данных."""
        response = client.get("/api/v1/accounts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["data"] == []
        assert data["meta"]["total"] == 0

    def test_empty_attempts_list_returns_empty(self, client: TestClient, auth_headers: dict):
        """GET /attempts возвращает пустой список если нет данных."""
        response = client.get("/api/v1/attempts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["data"] == []
        assert data["meta"]["total"] == 0


# =============================================================================
# I7.2: Формат ответа соответствует спецификации (контрактное тестирование)
# =============================================================================

class TestI72_ResponseFormat:
    """Тест I7.2: Ответы соответствуют формату из api-design.md."""

    def test_accounts_list_format(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Проверяет формат списка аккаунтов."""
        response = client.get("/api/v1/accounts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        assert "meta" in data

        if data["data"]:
            account = data["data"][0]
            required_fields = ["id", "cn", "valid_from", "valid_to", "is_revoked", "has_ccd", "created_at"]
            for field in required_fields:
                assert field in account, f"Missing field: {field}"

    def test_account_detail_format(self, client: TestClient, sample_account: Account, auth_headers: dict):
        """Проверяет формат деталей аккаунта."""
        response = client.get(f"/api/v1/accounts/{sample_account.cn}", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        required_fields = [
            "id", "cn", "valid_from", "valid_to", "is_revoked", "revoked_at",
            "has_ccd", "can_connect", "created_at", "updated_at", "last_session"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_sessions_list_format(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Проверяет формат списка сессий."""
        response = client.get("/api/v1/sessions", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        assert "meta" in data

        if data["data"]:
            session = data["data"][0]
            required_fields = [
                "id", "account_cn", "connected_at", "disconnected_at",
                "duration_seconds", "source_ip", "geo", "virtual_ip",
                "status", "bytes_sent", "bytes_received"
            ]
            for field in required_fields:
                assert field in session, f"Missing field: {field}"

            # Проверяем структуру geo
            geo = session["geo"]
            assert "country" in geo
            assert "country_code" in geo
            assert "city" in geo

    def test_active_sessions_format(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Проверяет формат списка активных сессий."""
        response = client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "count" in data
        assert "data" in data

        if data["data"]:
            session = data["data"][0]
            required_fields = ["id", "account_cn", "connected_at", "source_ip", "country", "city", "virtual_ip"]
            for field in required_fields:
                assert field in session, f"Missing field: {field}"

    def test_attempts_list_format(self, client: TestClient, sample_attempts: list, auth_headers: dict):
        """Проверяет формат списка попыток."""
        response = client.get("/api/v1/attempts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        assert "meta" in data

        if data["data"]:
            attempt = data["data"][0]
            required_fields = [
                "id", "account", "attempted_at", "source_ip",
                "cert_cn", "failure_reason", "failure_type", "details"
            ]
            for field in required_fields:
                assert field in attempt, f"Missing field: {field}"

            # Проверяем структуру account
            account = attempt["account"]
            assert "cn" in account
            assert "prefix" in account

    def test_stats_overview_format(self, client: TestClient, sample_accounts: list, sample_sessions: list, auth_headers: dict):
        """Проверяет формат общей статистики."""
        response = client.get("/api/v1/stats/overview", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "accounts" in data
        assert "sessions" in data
        assert "attempts" in data

        # Проверяем accounts
        accounts = data["accounts"]
        assert "total" in accounts
        assert "active_certs" in accounts
        assert "revoked" in accounts
        assert "with_ccd" in accounts
        assert "expiring_soon" in accounts

        # Проверяем sessions
        sessions = data["sessions"]
        assert "active" in sessions
        assert "today" in sessions
        assert "this_week" in sessions
        assert "this_month" in sessions

        # Проверяем attempts
        attempts = data["attempts"]
        assert "failed_today" in attempts
        assert "failed_this_week" in attempts
