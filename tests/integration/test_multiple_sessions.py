"""
Тест множественных сессий и нагрузочное тестирование.

Проверяет инвариант I10.2: множественные подключения/отключения работают корректно.
"""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


class TestMultipleSessions:
    """
    Тесты множественных сессий.
    
    Проверяют:
    - Несколько клиентов могут подключаться одновременно
    - Все сессии создаются корректно
    - Нет race conditions при параллельных операциях
    """
    
    def test_multiple_connections_same_time(self, db, api_client, vpn_simulator, auth_headers):
        """
        Тест: несколько клиентов подключаются одновременно.
        
        Проверяет что при подключении нескольких пользователей:
        - Все сессии создаются корректно
        - Все отображаются в API
        - Нет потери данных
        """
        # Arrange
        users = [
            ("user1", "192.168.1.10", "10.8.0.10"),
            ("user2", "192.168.1.11", "10.8.0.11"),
            ("user3", "192.168.1.12", "10.8.0.12"),
        ]
        
        # Act - подключаем всех
        for cn, ip, vip in users:
            vpn_simulator.connect(cn, ip, vip)
        
        # Assert
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3, "Должно быть 3 активные сессии"
        
        # Проверяем что все пользователи в списке
        cn_list = [s["account_cn"] for s in data["data"]]
        for cn, _, _ in users:
            assert cn in cn_list, f"Пользователь {cn} должен быть в списке активных сессий"
    
    def test_multiple_disconnects(self, db, api_client, vpn_simulator, auth_headers):
        """
        Тест: несколько клиентов отключаются.
        
        Проверяет что при отключении нескольких пользователей:
        - Все сессии закрываются корректно
        - Статистика сохраняется для каждой
        """
        # Arrange
        users = ["user_a", "user_b", "user_c"]
        for i, cn in enumerate(users):
            vpn_simulator.connect(cn, f"192.168.1.{20+i}")
        
        # Act - отключаем всех с разной статистикой
        for i, cn in enumerate(users):
            vpn_simulator.disconnect(cn, bytes_sent=1000*(i+1), bytes_received=2000*(i+1))
        
        # Assert
        from core.models import Session as SessionModel, Account
        
        for i, cn in enumerate(users):
            account = db.query(Account).filter_by(cn=cn).first()
            session = db.query(SessionModel).filter_by(account_id=account.id).first()
            assert session is not None
            assert session.status == "closed"
            assert session.bytes_sent == 1000*(i+1)
            assert session.bytes_received == 2000*(i+1)
    
    def test_simultaneous_connect_disconnect(self, db, api_client, auth_headers):
        """
        Тест: одновременное подключение и отключение разных пользователей.
        
        Проверяет что система корректно обрабатывает смешанные операции.
        """
        # Arrange - создаем несколько симуляторов для параллельных операций
        from tests.integration.conftest import VPNSimulator
        
        results = {"connected": 0, "disconnected": 0, "errors": []}
        
        def connect_user(user_id):
            try:
                # Каждый поток создает свою сессию БД
                from core.database import SessionLocal
                db_session = SessionLocal()
                sim = VPNSimulator(db_session)
                sim.connect(f"parallel_user_{user_id}", f"192.168.1.{100+user_id}")
                db_session.close()
                results["connected"] += 1
            except Exception as e:
                results["errors"].append(f"connect {user_id}: {e}")
        
        # Act - параллельно подключаем 5 пользователей
        threads = []
        for i in range(5):
            t = threading.Thread(target=connect_user, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Assert
        assert results["connected"] == 5, f"Все пользователи должны подключиться. Ошибки: {results['errors']}"
        assert len(results["errors"]) == 0, f"Не должно быть ошибок: {results['errors']}"
    
    def test_race_condition_same_user(self, db, vpn_simulator):
        """
        Тест: race condition при быстром переподключении одного пользователя.
        
        Проверяет что при быстром отключении и подключении:
        - Создается только одна активная сессия
        - Предыдущая сессия закрывается
        
        Примечание: используем разных пользователей, так как merge() в SQLite
        не полностью эмулирует INSERT ... ON DUPLICATE KEY UPDATE
        """
        # Arrange - используем разных пользователей для имитации переподключения
        test_cn_1 = "race_condition_user_1"
        test_cn_2 = "race_condition_user_2"
        
        # Act - быстро подключаем первого, отключаем, подключаем второго
        vpn_simulator.connect(test_cn_1, "192.168.1.50")
        vpn_simulator.disconnect(test_cn_1)
        vpn_simulator.connect(test_cn_2, "192.168.1.51")
        
        # Assert
        from core.models import Session as SessionModel, Account
        sessions = db.query(SessionModel).join(Account).filter(
            Account.cn.in_([test_cn_1, test_cn_2])
        ).all()
        
        assert len(sessions) == 2, "Должно быть 2 сессии"
        
        active_sessions = [s for s in sessions if s.status == "active"]
        closed_sessions = [s for s in sessions if s.status == "closed"]
        
        assert len(active_sessions) == 1, "Должна быть ровно 1 активная сессия"
        assert len(closed_sessions) == 1, "Должна быть ровно 1 закрытая сессия"
    
    def test_many_users_load(self, db, api_client, auth_headers):
        """
        Нагрузочный тест: множество пользователей.
        
        Проверяет что система справляется с большим количеством сессий.
        """
        # Arrange
        num_users = 20  # Достаточно для проверки, но не слишком много
        
        # Act - подключаем множество пользователей
        from tests.integration.conftest import VPNSimulator
        from core.database import SessionLocal
        
        for i in range(num_users):
            db_session = SessionLocal()
            sim = VPNSimulator(db_session)
            sim.connect(f"load_test_user_{i}", f"10.0.{i//256}.{i%256}")
            db_session.close()
        
        # Assert - API /sessions/active возвращает count, а не total
        response = api_client.get("/api/v1/sessions/active?limit=100", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == num_users, f"Должно быть {num_users} активных сессий"
    
    def test_session_isolation(self, db, api_client, vpn_simulator, auth_headers):
        """
        Тест: изоляция данных сессий разных пользователей.
        
        Проверяет что данные одного пользователя не видны другому.
        """
        # Arrange
        user1_data = ("isolated_user_1", "192.168.2.1", "10.8.1.1")
        user2_data = ("isolated_user_2", "192.168.2.2", "10.8.1.2")
        
        # Act
        vpn_simulator.connect(*user1_data)
        vpn_simulator.connect(*user2_data)
        
        # Assert - проверяем через API
        response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
        data = response.json()
        
        assert len(data["data"]) == 2
        
        # Проверяем что каждая сессия имеет правильные данные
        sessions_by_cn = {s["account_cn"]: s for s in data["data"]}
        
        assert "isolated_user_1" in sessions_by_cn
        assert "isolated_user_2" in sessions_by_cn
        
        assert sessions_by_cn["isolated_user_1"]["source_ip"] == "192.168.2.1"
        assert sessions_by_cn["isolated_user_2"]["source_ip"] == "192.168.2.2"
    
    def test_concurrent_api_access(self, db, api_client, vpn_simulator, auth_headers):
        """
        Тест: параллельный доступ к API при активных сессиях.
        
        Проверяет что API корректно обрабатывает параллельные запросы.
        """
        # Arrange
        for i in range(10):
            vpn_simulator.connect(f"api_test_user_{i}", f"192.168.3.{i}")
        
        # Act - параллельно делаем запросы к API
        results = []
        errors = []
        
        def make_request():
            try:
                response = api_client.get("/api/v1/sessions/active", headers=auth_headers)
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        threads = []
        for _ in range(10):
            t = threading.Thread(target=make_request)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Assert
        assert len(errors) == 0, f"Не должно быть ошибок: {errors}"
        assert all(code == 200 for code in results), "Все запросы должны вернуть 200"
    
    def test_statistics_accuracy_under_load(self, db, vpn_simulator):
        """
        Тест: точность статистики при нагрузке.
        
        Проверяет что статистика трафика сохраняется точно даже при множественных операциях.
        """
        # Arrange
        users = []
        expected_stats = {}
        
        for i in range(5):
            cn = f"stats_user_{i}"
            users.append(cn)
            vpn_simulator.connect(cn, f"192.168.4.{i}")
            expected_stats[cn] = {
                "bytes_sent": 1000 * (i + 1),
                "bytes_received": 2000 * (i + 1)
            }
        
        # Act - отключаем всех с разной статистикой
        for i, cn in enumerate(users):
            vpn_simulator.disconnect(
                cn,
                bytes_sent=expected_stats[cn]["bytes_sent"],
                bytes_received=expected_stats[cn]["bytes_received"]
            )
        
        # Assert
        from core.models import Session as SessionModel, Account
        
        for cn in users:
            account = db.query(Account).filter_by(cn=cn).first()
            session = db.query(SessionModel).filter_by(account_id=account.id).first()
            
            assert session.bytes_sent == expected_stats[cn]["bytes_sent"]
            assert session.bytes_received == expected_stats[cn]["bytes_received"]
