"""
Тест устойчивости системы к перезапуску и сбоям.

Проверяет инвариант I10.4: система устойчива к перезапуску.
"""

import pytest
from datetime import datetime, timedelta


class TestResilience:
    """
    Тесты устойчивости системы.
    
    Проверяют:
    - Данные сохраняются после перезапуска
    - Сессии корректно восстанавливаются
    - Нет потери данных при сбоях
    """
    
    def test_data_persistence_after_restart(self, db, api_client, vpn_simulator, auth_headers, restart_services):
        """
        Тест: данные сохраняются после перезапуска сервисов.
        
        Проверяет что после restart_services():
        - Сессии остаются в БД
        - Данные доступны через API
        """
        # Arrange - создаем данные
        test_cn = "persistent_user"
        test_ip = "192.168.5.100"
        vpn_simulator.connect(test_cn, test_ip)
        
        # Проверяем что данные есть
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        assert len(response.json()["data"]) == 1
        
        # Act - симулируем перезапуск
        restart_services()
        
        # Assert - данные должны сохраниться
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["account_cn"] == test_cn
    
    def test_active_session_preserved_after_restart(self, db, api_client, vpn_simulator, auth_headers, restart_services):
        """
        Тест: активная сессия сохраняет статус после перезапуска.
        
        Проверяет что активная сессия остается активной после перезапуска.
        """
        # Arrange
        test_cn = "active_after_restart"
        vpn_simulator.connect(test_cn, "192.168.5.101")
        
        # Act
        restart_services()
        
        # Assert
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        data = response.json()
        assert len(data["data"]) == 1
        # API /sessions/active возвращает только активные сессии без поля status
        assert data["data"][0]["account_cn"] == test_cn
    
    def test_closed_session_preserved_after_restart(self, db, api_client, vpn_simulator, auth_headers, restart_services):
        """
        Тест: закрытая сессия сохраняет статус после перезапуска.
        
        Проверяет что закрытая сессия остается закрытой после перезапуска.
        """
        # Arrange
        test_cn = "closed_after_restart"
        vpn_simulator.connect(test_cn, "192.168.5.102")
        vpn_simulator.disconnect(test_cn, bytes_sent=5000, bytes_received=10000)
        
        # Act
        restart_services()
        
        # Assert
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["status"] == "closed"
        assert data["data"][0]["bytes_sent"] == 5000
        assert data["data"][0]["bytes_received"] == 10000
    
    def test_account_data_preserved_after_restart(self, db, api_client, sample_data_factory, auth_headers, restart_services):
        """
        Тест: данные аккаунта сохраняются после перезапуска.
        
        Проверяет что метаданные аккаунта (valid_from, valid_to, etc.) сохраняются.
        """
        # Arrange
        account = sample_data_factory.create_account(
            cn="resilient_account",
            valid_from=datetime.utcnow() - timedelta(days=100),
            valid_to=datetime.utcnow() + timedelta(days=200),
            is_revoked=True,
            has_ccd=True
        )
        
        # Act
        restart_services()
        
        # Assert
        response = api_client.get("/api/v1/accounts/resilient_account", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data["cn"] == "resilient_account"
        assert data["has_ccd"] is True
        # Multi-cert: параметры сертификата — внутри certificates[]
        assert data["cert_count"] >= 1
        cert = data["certificates"][0]
        assert cert["is_revoked"] is True
        assert cert["valid_from"] is not None
        assert cert["valid_to"] is not None
    
    def test_multiple_sessions_preserved_after_restart(self, db, api_client, vpn_simulator, auth_headers, restart_services):
        """
        Тест: множественные сессии сохраняются после перезапуска.
        
        Проверяет что все сессии (активные и закрытые) сохраняются.
        """
        # Arrange
        users = [
            ("multi_resilient_1", "192.168.6.1"),
            ("multi_resilient_2", "192.168.6.2"),
            ("multi_resilient_3", "192.168.6.3"),
        ]
        
        # Подключаем всех
        for cn, ip in users:
            vpn_simulator.connect(cn, ip)
        
        # Отключаем одного
        vpn_simulator.disconnect(users[0][0])
        
        # Act
        restart_services()
        
        # Assert
        # Проверяем активные сессии
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        active_data = response.json()
        # API /sessions/active возвращает count, а не total
        assert active_data["count"] == 2
        
        # Проверяем все сессии
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        all_data = response.json()
        assert all_data["meta"]["total"] == 3
        
        # Проверяем что закрытая сессия на месте
        closed_sessions = [s for s in all_data["data"] if s["status"] == "closed"]
        assert len(closed_sessions) == 1
        assert closed_sessions[0]["account_cn"] == users[0][0]
    
    def test_statistics_preserved_after_restart(self, db, api_client, vpn_simulator, auth_headers, restart_services):
        """
        Тест: статистика сохраняется после перезапуска.
        
        Проверяет что bytes_sent/bytes_received сохраняются.
        """
        # Arrange
        test_cn = "stats_resilient_user"
        vpn_simulator.connect(test_cn, "192.168.6.10")
        vpn_simulator.disconnect(test_cn, bytes_sent=9999, bytes_received=8888)
        
        # Act
        restart_services()
        
        # Assert
        response = api_client.get("/api/v1/sessions/", headers=auth_headers)
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["bytes_sent"] == 9999
        assert data["data"][0]["bytes_received"] == 8888
    
    
    def test_geoip_cache_preserved_after_restart(self, db, sample_data_factory, restart_services):
        """
        Тест: кэш GeoIP сохраняется после перезапуска.
        
        Проверяет что кэшированные данные геолокации сохраняются.
        """
        # Arrange
        from core.models import GeoIPCache
        
        cache_entry = GeoIPCache(
            ip="8.8.8.8",
            country="United States",
            country_code="US",
            city="Mountain View",
            region="California",
            latitude=37.386051,
            longitude=-122.083847,
            isp="Google LLC",
            cached_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.add(cache_entry)
        db.commit()
        
        # Act
        restart_services()
        
        # Assert
        cached = db.query(GeoIPCache).filter_by(ip="8.8.8.8").first()
        assert cached is not None
        assert cached.country == "United States"
        assert cached.city == "Mountain View"
    
    def test_session_continues_after_partial_restart(self, db, api_client, vpn_simulator, auth_headers):
        """
        Тест: сессия продолжает существовать после частичного перезапуска.
        
        Проверяет что активная сессия остается активной даже если
        приложение перезапускается во время сессии.
        """
        # Arrange
        test_cn = "continues_session_user"
        vpn_simulator.connect(test_cn, "192.168.7.1")
        
        # Act - симулируем перезапуск без отключения
        from web.main import app
        from core.database import get_db
        
        # Очищаем overrides
        app.dependency_overrides.clear()
        
        # Восстанавливаем соединение
        def _get_db_override():
            try:
                yield db
            finally:
                pass
        
        app.dependency_overrides[get_db] = _get_db_override
        
        # Assert - сессия должна быть активной
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["account_cn"] == test_cn
        # API /sessions/active не возвращает поле status
    
    def test_no_data_loss_during_high_load(self, db, api_client, auth_headers):
        """
        Тест: отсутствие потери данных при высокой нагрузке.
        
        Проверяет что при создании множества записей все сохраняются.
        """
        # Arrange
        from tests.integration.conftest import VPNSimulator
        from core.database import SessionLocal
        
        num_sessions = 50
        
        # Act - создаем множество сессий
        for i in range(num_sessions):
            db_session = SessionLocal()
            sim = VPNSimulator(db_session)
            sim.connect(f"load_user_{i}", f"10.1.{i//256}.{i%256}")
            db_session.close()
        
        # Assert - API /sessions/active возвращает count, а не total
        response = api_client.get("/api/v1/sessions/active?limit=100", headers=auth_headers)
        data = response.json()
        assert data["count"] == num_sessions, f"Должно быть {num_sessions} сессий"
    
    def test_database_integrity_after_operations(self, db, vpn_simulator):
        """
        Тест: целостность базы данных после множественных операций.
        
        Проверяет что внешние ключи и ограничения не нарушаются.
        """
        # Arrange & Act - выполняем множество операций
        from core.models import Account, Session as SessionModel
        
        # Создаем и закрываем сессии
        for i in range(10):
            cn = f"integrity_user_{i}"
            vpn_simulator.connect(cn, f"192.168.8.{i}")
            if i % 2 == 0:
                vpn_simulator.disconnect(cn)
        
        # Assert - проверяем целостность
        # Все сессии должны иметь валидный account_id
        sessions = db.query(SessionModel).all()
        for session in sessions:
            account = db.query(Account).filter_by(id=session.account_id).first()
            assert account is not None, f"Сессия {session.id} должна иметь валидный account_id"
        
        # Все аккаунты должны иметь уникальный CN
        accounts = db.query(Account).all()
        cn_set = set()
        for account in accounts:
            assert account.cn not in cn_set, f"CN {account.cn} должен быть уникальным"
            cn_set.add(account.cn)
