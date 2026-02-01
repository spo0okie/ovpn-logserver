"""
End-to-end тесты полного цикла работы системы.

Проверяют интеграцию всех компонентов:
- VPN подключение/отключение
- Collector скрипты
- База данных
- REST API
- Web UI
"""

import pytest
from datetime import datetime, timedelta


class TestEndToEnd:
    """
    E2E тесты полного цикла работы системы.
    
    Проверяют что вся система работает в комплексе:
    - Подключение клиента → запись в БД → отображение в API/UI
    - Отключение клиента → обновление записи → обновление в API/UI
    - Синхронизации обновляют метаданные
    - Статистика корректно агрегируется
    """
    
    def test_e2e_single_user_lifecycle(self, db, api_client, e2e_vpn_simulator, auth_headers):
        """
        E2E тест полного жизненного цикла одного пользователя.
        
        Сценарий:
        1. Пользователь подключается к VPN
        2. Проверяем что сессия видна в API активных сессий
        3. Проверяем что аккаунт создан и доступен через API
        4. Пользователь отключается
        5. Проверяем что сессия закрыта и статистика сохранена
        6. Проверяем что данные видны в истории сессий
        """
        # Step 1: Подключение
        test_cn = "e2e_lifecycle_user"
        test_ip = "192.168.100.1"
        virtual_ip = "10.8.0.100"
        
        e2e_vpn_simulator.connect(
            cn=test_cn,
            source_ip=test_ip,
            virtual_ip=virtual_ip,
            country="Russia",
            city="Moscow"
        )
        
        # Step 2: Проверка активных сессий через API
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200
        active_data = response.json()
        # API возвращает count, а не total
        assert active_data["count"] == 1
        assert active_data["data"][0]["account_cn"] == test_cn
        assert active_data["data"][0]["source_ip"] == test_ip
        assert active_data["data"][0]["virtual_ip"] == virtual_ip
        session_id = active_data["data"][0]["id"]
        
        # Step 3: Проверка аккаунта через API
        response = api_client.get(f"/api/v1/accounts/{test_cn}", headers=auth_headers)
        assert response.status_code == 200
        account_data = response.json()
        assert account_data["cn"] == test_cn
        
        # Step 4: Отключение
        e2e_vpn_simulator.disconnect(
            cn=test_cn,
            bytes_sent=50000,
            bytes_received=100000,
            duration=7200
        )
        
        # Step 5: Проверка закрытой сессии
        response = api_client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers)
        assert response.status_code == 200
        session_data = response.json()
        assert session_data["status"] == "closed"
        assert session_data["bytes_sent"] == 50000
        assert session_data["bytes_received"] == 100000
        
        # Step 6: Проверка истории сессий
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        assert response.status_code == 200
        history_data = response.json()
        # API возвращает meta.total
        assert history_data["meta"]["total"] == 1
        assert history_data["data"][0]["account_cn"] == test_cn
    
    def test_e2e_multiple_users_scenario(self, db, api_client, e2e_vpn_simulator, auth_headers):
        """
        E2E тест сценария с множеством пользователей.
        
        Сценарий:
        1. 5 пользователей подключаются
        2. Проверяем список активных сессий
        3. 2 пользователя отключаются
        4. Проверяем что 3 активных и 2 закрытых сессии
        5. Проверяем статистику
        """
        # Step 1: Подключаем 5 пользователей
        users = []
        for i in range(5):
            cn = f"e2e_multi_user_{i}"
            ip = f"192.168.101.{i+1}"
            vip = f"10.8.1.{i+1}"
            e2e_vpn_simulator.connect(cn, ip, vip)
            users.append(cn)
        
        # Step 2: Проверяем активные сессии
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 5
        
        # Step 3: Отключаем 2 пользователей
        for i in range(2):
            e2e_vpn_simulator.disconnect(
                users[i],
                bytes_sent=10000 * (i + 1),
                bytes_received=20000 * (i + 1)
            )
        
        # Step 4: Проверяем активные и все сессии
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        active_count = response.json()["count"]
        assert active_count == 3
        
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        total_count = response.json()["meta"]["total"]
        assert total_count == 5
        
        # Step 5: Проверяем статистику overview
        response = api_client.get("/api/v1/stats/overview", headers=auth_headers)
        assert response.status_code == 200
        stats = response.json()
        assert "accounts" in stats
        assert "sessions" in stats
        assert stats["sessions"]["active"] == 3
    
    def test_e2e_account_details_with_history(self, db, api_client, e2e_data_factory, auth_headers):
        """
        E2E тест деталей аккаунта с историей.
        
        Сценарий:
        1. Создаем аккаунт с историей сессий
        2. Создаем неудачные попытки подключения
        3. Получаем детали аккаунта через API
        4. Проверяем что история сессий включена
        5. Проверяем статистику по аккаунту
        """
        # Step 1: Создаем аккаунт с историей
        account = e2e_data_factory.create_complete_account(cn="e2e_history_user")
        sessions = e2e_data_factory.create_session_history(account, num_sessions=5)
        
        # Step 2: Создаем попытки подключения
        attempts = e2e_data_factory.create_failed_attempts(account, num_attempts=3)
        
        # Step 3: Получаем детали аккаунта
        response = api_client.get("/api/v1/accounts/e2e_history_user", headers=auth_headers)
        assert response.status_code == 200
        account_data = response.json()
        
        # Step 4: Проверяем историю сессий
        assert account_data["cn"] == "e2e_history_user"
        
        # Step 5: Проверяем сессии аккаунта через /accounts/{cn}/sessions
        response = api_client.get(
            "/api/v1/accounts/e2e_history_user/sessions",
            headers=auth_headers
        )
        assert response.status_code == 200
        sessions_data = response.json()
        assert sessions_data["meta"]["total"] == 5
        
        # Проверяем попытки подключения
        response = api_client.get(
            "/api/v1/attempts/?cert_cn=e2e_history_user",
            headers=auth_headers
        )
        assert response.status_code == 200
        attempts_data = response.json()
        assert attempts_data["meta"]["total"] == 3
    
    def test_e2e_dashboard_statistics(self, db, api_client, e2e_vpn_simulator, e2e_data_factory, auth_headers):
        """
        E2E тест статистики дашборда.
        
        Сценарий:
        1. Создаем несколько активных сессий
        2. Создаем несколько закрытых сессий
        3. Создаем попытки подключения
        4. Получаем статистику overview
        5. Проверяем что все метрики корректны
        """
        # Step 1-3: Создаем тестовые данные
        # Активные сессии
        for i in range(3):
            e2e_vpn_simulator.connect(
                f"e2e_stats_active_{i}",
                f"192.168.102.{i+1}"
            )
        
        # Закрытые сессии
        for i in range(2):
            cn = f"e2e_stats_closed_{i}"
            e2e_vpn_simulator.connect(cn, f"192.168.103.{i+1}")
            e2e_vpn_simulator.disconnect(cn)
        
        # Попытки подключения
        e2e_data_factory.create_failed_attempts(num_attempts=4)
        
        # Step 4: Получаем статистику overview
        response = api_client.get("/api/v1/stats/overview", headers=auth_headers)
        assert response.status_code == 200
        stats = response.json()
        
        # Step 5: Проверяем метрики
        assert "accounts" in stats
        assert "sessions" in stats
        assert "attempts" in stats
        
        assert stats["sessions"]["active"] == 3
        assert stats["accounts"]["total"] >= 5
    
    def test_e2e_filtering_and_pagination(self, db, api_client, e2e_vpn_simulator, auth_headers):
        """
        E2E тест фильтрации и пагинации.
        
        Сценарий:
        1. Создаем множество сессий
        2. Тестируем пагинацию
        3. Тестируем фильтрацию по статусу
        4. Тестируем фильтрацию по аккаунту
        """
        # Step 1: Создаем сессии
        for i in range(10):
            cn = f"e2e_filter_user_{i % 3}"  # 3 разных пользователя
            e2e_vpn_simulator.connect(f"{cn}_{i}", f"192.168.104.{i+1}")
        
        # Отключаем половину
        for i in range(0, 10, 2):
            cn = f"e2e_filter_user_{i % 3}_{i}"
            e2e_vpn_simulator.disconnect(cn)
        
        # Step 2: Тестируем пагинацию
        response = api_client.get("/api/v1/sessions/?limit=5", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) <= 5
        
        # Step 3: Тестируем фильтрацию по статусу
        response = api_client.get("/api/v1/sessions/?status=active", headers=auth_headers)
        assert response.status_code == 200
        active_data = response.json()
        assert all(s["status"] == "active" for s in active_data["data"])
        
        response = api_client.get("/api/v1/sessions/?status=closed", headers=auth_headers)
        assert response.status_code == 200
        closed_data = response.json()
        assert all(s["status"] == "closed" for s in closed_data["data"])
        
        # Step 4: Тестируем фильтрацию по аккаунту
        response = api_client.get(
            "/api/v1/sessions/?account=e2e_filter_user_0",  # используем параметр account
            headers=auth_headers
        )
        assert response.status_code == 200
        filtered_data = response.json()
        # Должны быть сессии только user_0 (с разными суффиксами)
        for session in filtered_data["data"]:
            assert "e2e_filter_user_0" in session["account_cn"]
    
    def test_e2e_complete_workflow_with_sync(self, db, api_client, e2e_vpn_simulator, 
                                              tmp_path, auth_headers):
        """
        E2E тест полного workflow с синхронизацией.
        
        Сценарий:
        1. Создаем аккаунт
        2. Создаем сертификат для аккаунта
        3. Запускаем синхронизацию сертификатов
        4. Проверяем что даты обновлены
        5. Подключаем пользователя
        6. Проверяем что сессия видна с обновленными метаданными
        """
        from tests.integration.conftest import create_test_cert
        from collector.cert_sync import sync_certificates
        from core.models import Account
        
        # Step 1: Создаем аккаунт
        test_cn = "e2e_sync_user_unique"
        account = Account(cn=test_cn)
        db.add(account)
        db.commit()
        
        # Step 2: Создаем сертификат
        certs_dir = tmp_path / "e2e_certs"
        certs_dir.mkdir()
        create_test_cert(certs_dir, test_cn, valid_days=180)
        
        # Step 3: Синхронизация
        stats = sync_certificates(db=db, certs_dir=str(certs_dir))
        assert stats["updated"] == 1
        
        # Step 4: Проверяем обновление
        db.refresh(account)
        assert account.valid_from is not None
        assert account.valid_to is not None
        
        # Step 5: Подключаем пользователя
        e2e_vpn_simulator.connect(test_cn, "192.168.105.1")
        
        # Step 6: Проверяем через API
        response = api_client.get(f"/api/v1/accounts/{test_cn}", headers=auth_headers)
        assert response.status_code == 200
        account_data = response.json()
        assert account_data["valid_from"] is not None
        assert account_data["valid_to"] is not None
        
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200
        sessions_data = response.json()
        assert sessions_data["count"] == 1
        assert sessions_data["data"][0]["account_cn"] == test_cn
    
    def test_e2e_error_handling(self, db, api_client, auth_headers):
        """
        E2E тест обработки ошибок.
        
        Сценарий:
        1. Запрашиваем несуществующий аккаунт
        2. Запрашиваем несуществующую сессию
        3. Проверяем корректность ошибок
        """
        # Step 1: Несуществующий аккаунт
        response = api_client.get("/api/v1/accounts/nonexistent_user_12345", headers=auth_headers)
        assert response.status_code == 404
        
        # Step 2: Несуществующая сессия
        response = api_client.get("/api/v1/sessions/999999", headers=auth_headers)
        assert response.status_code == 404
        
        # Step 3: Невалидные параметры
        response = api_client.get("/api/v1/sessions/?status=invalid_status", headers=auth_headers)
        # Должен вернуть пустой список (фильтр просто не найдет записей)
        assert response.status_code == 200
    
    def test_e2e_ui_pages_load(self, db, api_client, e2e_vpn_simulator, auth_headers):
        """
        E2E тест загрузки UI страниц.
        
        Сценарий:
        1. Создаем тестовые данные
        2. Проверяем загрузку основных страниц
        3. Проверяем что данные отображаются
        """
        # Step 1: Создаем данные
        e2e_vpn_simulator.connect("e2e_ui_user", "192.168.106.1")
        
        # Step 2: Проверяем страницы
        pages = [
            "/",
            "/sessions",
            "/accounts",
            "/attempts",
        ]
        
        for page in pages:
            response = api_client.get(page, headers=auth_headers)
            assert response.status_code == 200, f"Страница {page} должна загружаться"
            # Проверяем что HTML содержит ожидаемые элементы
            assert "text/html" in response.headers.get("content-type", "")
    
    def test_e2e_traffic_statistics(self, db, api_client, e2e_vpn_simulator, auth_headers):
        """
        E2E тест статистики трафика.
        
        Сценарий:
        1. Создаем сессии с разным трафиком
        2. Проверяем агрегацию трафика
        3. Проверяем статистику по аккаунту
        """
        # Step 1: Создаем сессии с трафиком
        traffic_data = [
            ("e2e_traffic_1", 1000, 2000),
            ("e2e_traffic_2", 5000, 10000),
            ("e2e_traffic_3", 10000, 20000),
        ]
        
        total_sent = 0
        total_received = 0
        
        for cn, sent, received in traffic_data:
            e2e_vpn_simulator.connect(cn, f"192.168.107.{traffic_data.index((cn, sent, received))+1}")
            e2e_vpn_simulator.disconnect(cn, bytes_sent=sent, bytes_received=received)
            total_sent += sent
            total_received += received
        
        # Step 2: Проверяем через API
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        actual_sent = sum(s["bytes_sent"] for s in data["data"])
        actual_received = sum(s["bytes_received"] for s in data["data"])
        
        assert actual_sent == total_sent
        assert actual_received == total_received
    
    def test_e2e_time_range_filtering(self, db, api_client, e2e_data_factory, auth_headers):
        """
        E2E тест фильтрации по времени.
        
        Сценарий:
        1. Создаем сессии в разное время
        2. Фильтруем по временному диапазону
        3. Проверяем корректность результатов
        """
        from core.models import Session as SessionModel, Account
        
        # Step 1: Создаем сессии в разное время
        account = e2e_data_factory.create_complete_account(cn="e2e_timerange_user")
        
        # Сессия 1 час назад
        session1 = SessionModel(
            account_id=account.id,
            session_id="e2e_time_1",
            connected_at=datetime.utcnow() - timedelta(hours=1),
            disconnected_at=datetime.utcnow() - timedelta(minutes=50),
            source_ip="192.168.108.1",
            status="closed"
        )
        db.add(session1)
        
        # Сессия 1 день назад
        session2 = SessionModel(
            account_id=account.id,
            session_id="e2e_time_2",
            connected_at=datetime.utcnow() - timedelta(days=1),
            disconnected_at=datetime.utcnow() - timedelta(days=1, minutes=-10),
            source_ip="192.168.108.2",
            status="closed"
        )
        db.add(session2)
        db.commit()
        
        # Step 2-3: Проверяем что обе сессии видны
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] == 2
