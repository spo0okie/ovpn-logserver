"""
Функциональные тесты API endpoints.
"""

import base64
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.models import Account, Session as SessionModel, ConnectionAttempt


class TestAccountsAPI:
    """Тесты для endpoints аккаунтов."""

    def test_list_accounts_success(self, client: TestClient, sample_accounts: list, auth_headers: dict):
        """Успешное получение списка аккаунтов."""
        response = client.get("/api/v1/accounts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 5
        assert data["meta"]["total"] == 5

    def test_get_account_success(self, client: TestClient, sample_account: Account, auth_headers: dict):
        """Успешное получение деталей аккаунта."""
        response = client.get(f"/api/v1/accounts/{sample_account.cn}", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["cn"] == sample_account.cn
        assert data["id"] == sample_account.id
        assert "can_connect" in data

    def test_get_account_sessions(self, client: TestClient, sample_account: Account, sample_sessions: list, auth_headers: dict):
        """Получение истории сессий аккаунта."""
        response = client.get(f"/api/v1/accounts/{sample_account.cn}/sessions", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 2
        assert data["meta"]["total"] == 2

    def test_get_account_sessions_not_found(self, client: TestClient, auth_headers: dict):
        """404 при запросе сессий несуществующего аккаунта."""
        response = client.get("/api/v1/accounts/nonexistent/sessions", headers=auth_headers)
        assert response.status_code == 404


class TestSessionsAPI:
    """Тесты для endpoints сессий."""

    def test_list_sessions_success(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Успешное получение списка сессий."""
        response = client.get("/api/v1/sessions", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 2

    def test_get_session_success(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Успешное получение деталей сессии."""
        session = sample_sessions[0]
        response = client.get(f"/api/v1/sessions/{session.id}", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == session.id
        assert "geo" in data
        assert "is_active" in data

    def test_list_active_sessions(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Получение списка активных сессий."""
        response = client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["count"] == 1  # Только одна активная сессия
        assert len(data["data"]) == 1


class TestAttemptsAPI:
    """Тесты для endpoints попыток подключения."""

    def test_list_attempts_success(self, client: TestClient, sample_attempts: list, auth_headers: dict):
        """Успешное получение списка попыток."""
        response = client.get("/api/v1/attempts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 3

    def test_list_attempts_empty(self, client: TestClient, auth_headers: dict):
        """Пустой список попыток."""
        response = client.get("/api/v1/attempts", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["data"] == []
        assert data["meta"]["total"] == 0


class TestStatsAPI:
    """Тесты для endpoints статистики."""

    def test_overview_stats(self, client: TestClient, sample_accounts: list, sample_sessions: list, auth_headers: dict):
        """Получение общей статистики."""
        response = client.get("/api/v1/stats/overview", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        # sample_accounts создает 5 аккаунтов
        assert data["accounts"]["total"] >= 5
        assert data["sessions"]["active"] >= 1

    def test_connections_stats(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Получение статистики подключений."""
        from_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
        to_date = datetime.utcnow().isoformat()

        response = client.get(
            f"/api/v1/stats/connections?from={from_date}&to={to_date}&group_by=day",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert data["group_by"] == "day"
        assert "data" in data

    def test_connections_stats_invalid_group_by(self, client: TestClient, auth_headers: dict):
        """Ошибка при неверном group_by."""
        from_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
        to_date = datetime.utcnow().isoformat()

        response = client.get(
            f"/api/v1/stats/connections?from={from_date}&to={to_date}&group_by=invalid",
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_failures_stats(self, client: TestClient, sample_attempts: list, auth_headers: dict):
        """Получение статистики ошибок."""
        from_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
        to_date = datetime.utcnow().isoformat()

        response = client.get(
            f"/api/v1/stats/failures?from={from_date}&to={to_date}&group_by=type",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert data["group_by"] == "type"
        assert len(data["data"]) > 0

    def test_geography_stats(self, client: TestClient, sample_sessions: list, auth_headers: dict):
        """Получение статистики по геолокации."""
        response = client.get("/api/v1/stats/geography?limit=5", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        # Должно быть 2 страны: Russia и Germany
        assert len(data["data"]) == 2


class TestMainEndpoints:
    """Тесты для корневых endpoints."""

    def test_root_endpoint(self, client: TestClient):
        """Корневой endpoint доступен без авторизации."""
        response = client.get("/", headers={"Accept": "application/json"})
        # Теперь корневой endpoint возвращает HTML (Dashboard UI), 
        # поэтому проверяем что он доступен (200) или перенаправляет на login (307/302)
        assert response.status_code in [200, 307, 302]
        if response.status_code == 200:
            # Если это HTML, проверяем что есть DOCTYPE или html тег
            if "text/html" in response.headers.get("content-type", ""):
                assert "<!DOCTYPE html>" in response.text or "<html" in response.text
            else:
                # Если JSON, проверяем структуру
                assert "name" in response.json()

    def test_health_endpoint(self, client: TestClient):
        """Health check доступен без авторизации."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
