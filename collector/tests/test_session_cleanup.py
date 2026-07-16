#!/usr/bin/env python3
"""
Тесты для модуля session_cleanup.py.

Проверяют инварианты:
- C1.1: Пропуск активных сессий
- C1.2: Неправильная логика сравнения
- C1.3: Изменение статуса не orphaned сессии
- C1.4: Отсутствие времени отключения
- C1.5: Потеря информации об orphaned сессиях
- C1.6: Повреждение данных при повторном запуске
"""

import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from pathlib import Path

# Добавляем родительские директории в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGetActiveSessions:
    """
    Тесты функции get_active_sessions (C1.1).
    """

    def test_c1_1_finds_all_active_sessions(self, db):
        """
        C1.1: Функция находит все сессии со статусом 'active'.

        Предотвращает: Пропуск активных сессий
        """
        from collector.session_cleanup import get_active_sessions
        from core.models import Account, Session

        # Создаем тестовые данные
        account = Account(cn="test_user", serial_number="test_serial")
        db.add(account)
        db.commit()

        # Создаем сессии с разными статусами
        active_session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        closed_session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=1),
            disconnected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='closed'
        )
        error_session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=2),
            disconnected_at=datetime.utcnow() - timedelta(hours=1),
            source_ip="10.0.0.1",
            status='error'
        )

        db.add_all([active_session, closed_session, error_session])
        db.commit()

        # Получаем активные сессии
        active_sessions = get_active_sessions(db)

        # Проверяем что нашли только активные
        assert len(active_sessions) == 1
        assert active_sessions[0].id == active_session.id
        assert active_sessions[0].status == 'active'

    def test_c1_1_returns_empty_list_when_no_active(self, db):
        """
        C1.1: Возвращает пустой список если нет активных сессий.

        Предотвращает: Пропуск активных сессий
        """
        from collector.session_cleanup import get_active_sessions

        # Не создаем сессий
        active_sessions = get_active_sessions(db)

        assert active_sessions == []


class TestGetOrphanedSessions:
    """
    Тесты функции get_orphaned_sessions (C1.2).
    """

    def test_c1_2_finds_orphaned_when_cn_not_in_mgmt(self, db):
        """
        C1.2: Находит orphaned сессию когда CN не в Management Interface.

        Предотвращает: Неправильная логика сравнения
        """
        from collector.session_cleanup import get_orphaned_sessions
        from core.models import Account, Session

        # Создаем аккаунт
        account = Account(cn="orphaned_user", serial_number="serial1")
        db.add(account)
        db.commit()

        # Создаем активную сессию
        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Список подключенных клиентов БЕЗ нашего пользователя
        connected_cns = {"other_user", "another_user"}

        # Ищем orphaned сессии
        orphaned = get_orphaned_sessions([session], connected_cns)

        # Наша сессия должна быть найдена как orphaned
        assert len(orphaned) == 1
        assert orphaned[0].id == session.id

    def test_c1_2_does_not_mark_connected_session(self, db):
        """
        C1.2: Не помечает как orphaned сессию с CN в Management Interface.

        Предотвращает: Неправильная логика сравнения
        """
        from collector.session_cleanup import get_orphaned_sessions
        from core.models import Account, Session

        # Создаем аккаунт
        account = Account(cn="active_user", serial_number="serial1")
        db.add(account)
        db.commit()

        # Создаем активную сессию
        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Список подключенных клиентов С нашим пользователем
        connected_cns = {"active_user", "other_user"}

        # Ищем orphaned сессии
        orphaned = get_orphaned_sessions([session], connected_cns)

        # Наша сессия НЕ должна быть найдена как orphaned
        assert len(orphaned) == 0

    def test_c1_2_handles_empty_connected_clients(self, db):
        """
        C1.2: Корректно работает с пустым списком подключенных клиентов.

        Предотвращает: Неправильная логика сравнения
        """
        from collector.session_cleanup import get_orphaned_sessions
        from core.models import Account, Session

        # Создаем аккаунт
        account = Account(cn="user1", serial_number="serial1")
        db.add(account)
        db.commit()

        # Создаем активные сессии
        session1 = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        session2 = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=1),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add_all([session1, session2])
        db.commit()

        # Пустой список подключенных
        connected_cns = set()

        # Ищем orphaned сессии
        orphaned = get_orphaned_sessions([session1, session2], connected_cns)

        # Все сессии должны быть orphaned
        assert len(orphaned) == 2


class TestMarkSessionAsOrphaned:
    """
    Тесты функции mark_session_as_orphaned (C1.3, C1.4, C1.5).
    """

    def test_c1_3_sets_status_to_error(self, db):
        """
        C1.3: Устанавливает статус 'error' для orphaned сессии.

        Предотвращает: Изменение статуса не orphaned сессии
        """
        from collector.session_cleanup import mark_session_as_orphaned
        from core.models import Account, Session

        # Создаем аккаунт и сессию
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Помечаем как orphaned
        mark_session_as_orphaned(db, session)

        # Проверяем статус
        db.refresh(session)
        assert session.status == 'error'

    def test_c1_4_sets_disconnected_at(self, db):
        """
        C1.4: Устанавливает disconnected_at для orphaned сессии.

        Предотвращает: Отсутствие времени отключения
        """
        from collector.session_cleanup import mark_session_as_orphaned
        from core.models import Account, Session

        # Создаем аккаунт и сессию
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        before_mark = datetime.utcnow()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Помечаем как orphaned
        mark_session_as_orphaned(db, session)

        # Проверяем disconnected_at
        db.refresh(session)
        assert session.disconnected_at is not None
        assert session.disconnected_at >= before_mark

    def test_c1_5_logs_orphaned_session(self, db, caplog):
        """
        C1.5: Логирует информацию об orphaned сессии.

        Предотвращает: Потеря информации об orphaned сессиях
        """
        from collector.session_cleanup import mark_session_as_orphaned
        from core.models import Account, Session
        import logging

        # Создаем аккаунт и сессию
        account = Account(cn="logged_user", serial_number="serial1")
        db.add(account)
        db.commit()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Помечаем как orphaned с логированием
        with caplog.at_level(logging.INFO):
            mark_session_as_orphaned(db, session)

        # Проверяем что залогировали
        assert "Orphaned session marked as error" in caplog.text
        assert "logged_user" in caplog.text
        assert str(session.id) in caplog.text


class TestCleanupOrphanedSessionsIdempotency:
    """
    Тесты идемпотентности (C1.6).
    """

    def test_c1_6_idempotent_second_run_no_change(self, db):
        """
        C1.6: Повторный запуск не изменяет уже помеченные сессии.

        Предотвращает: Повреждение данных при повторном запуске
        """
        from collector.session_cleanup import cleanup_orphaned_sessions
        from core.models import Account, Session

        # Создаем аккаунт и сессию
        account = Account(cn="idempotent_user", serial_number="serial1")
        db.add(account)
        db.commit()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        disconnected_before = None

        # Передаём непустое множество с другим CN — наш CN orphaned.
        # Пустое множество интерпретируется как «mgmt вернул 0 клиентов» и
        # триггерит fail-closed (см. session_cleanup C1.7).
        connected = {"someone_else"}

        # Первый запуск
        orphaned1, marked1 = cleanup_orphaned_sessions(db, connected)
        db.refresh(session)

        assert marked1 == 1
        assert session.status == 'error'
        disconnected_before = session.disconnected_at

        # Второй запуск - сессия уже помечена, не должна измениться
        orphaned2, marked2 = cleanup_orphaned_sessions(db, connected)

        db.refresh(session)

        # marked2 должен быть 0, так как сессия уже помечена
        assert marked2 == 0
        assert session.status == 'error'
        # disconnected_at не должен измениться
        assert session.disconnected_at == disconnected_before

    def test_c1_6_does_not_change_error_to_error_again(self, db):
        """
        C1.6: Повторный запуск не меняет уже закрытые error сессии.

        Предотвращает: Повреждение данных при повторном запуске
        """
        from collector.session_cleanup import cleanup_orphaned_sessions
        from core.models import Account, Session

        # Создаем аккаунт и сессию со статусом 'error'
        account = Account(cn="already_error_user", serial_number="serial1")
        db.add(account)
        db.commit()

        disconnected_time = datetime.utcnow() - timedelta(hours=1)

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=2),
            disconnected_at=disconnected_time,
            source_ip="10.0.0.1",
            status='error'
        )
        db.add(session)
        db.commit()

        # Запускаем очистку с пустым списком (сессия уже error, не должна измениться)
        orphaned, marked = cleanup_orphaned_sessions(db, set())

        db.refresh(session)

        # marked должен быть 0
        assert marked == 0
        # disconnected_at не должен измениться
        assert session.disconnected_at == disconnected_time


class TestIntegrationCleanup:
    """
    Интеграционные тесты полного цикла очистки.
    """

    def test_full_cleanup_flow(self, db):
        """
        Полный тест потока очистки: активные → orphaned → помеченные.
        """
        from collector.session_cleanup import cleanup_orphaned_sessions
        from core.models import Account, Session

        # Создаем несколько аккаунтов
        accounts = [
            Account(cn="connected_user", serial_number="serial1"),
            Account(cn="orphaned_user1", serial_number="serial2"),
            Account(cn="orphaned_user2", serial_number="serial3"),
        ]
        db.add_all(accounts)
        db.commit()

        # Создаем сессии
        sessions = [
            Session(account_id=accounts[0].id, connected_at=datetime.utcnow(), source_ip="10.0.0.1", status='active'),
            Session(account_id=accounts[1].id, connected_at=datetime.utcnow(), source_ip="10.0.0.1", status='active'),
            Session(account_id=accounts[2].id, connected_at=datetime.utcnow(), source_ip="10.0.0.1", status='active'),
        ]
        db.add_all(sessions)
        db.commit()

        # Только один пользователь подключен
        connected_cns = {"connected_user"}

        # Запускаем очистку
        orphaned, marked = cleanup_orphaned_sessions(db, connected_cns)

        # Проверяем результаты
        assert orphaned == 2
        assert marked == 2

        # Проверяем статусы
        db.refresh(sessions[0])
        db.refresh(sessions[1])
        db.refresh(sessions[2])

        assert sessions[0].status == 'active'  # Не изменился
        assert sessions[1].status == 'error'   # Помечен
        assert sessions[2].status == 'error'   # Помечен

    def test_handles_session_without_account(self, db):
        """
        Корректно обрабатывает сессию без связанного аккаунта (account_id=999).
        В тесте используется мок сессии, которая не имеет связанного аккаунта.
        """
        from collector.session_cleanup import get_orphaned_sessions
        from unittest.mock import MagicMock
        
        # Создаем мок-сессию без связанного аккаунта
        mock_session = MagicMock()
        mock_session.id = 1
        mock_session.account = None  # Нет связанного аккаунта
        mock_session.account_id = 999  # Несуществующий ID
        mock_session.cn = None
        
        # Любой список подключенных
        connected_cns = {"some_user"}
        
        # Сессия без аккаунта должна считаться orphaned
        orphaned = get_orphaned_sessions([mock_session], connected_cns)
        
        assert len(orphaned) == 1
        assert orphaned[0].id == mock_session.id


class TestMainFunction:
    """
    Тесты функции main().
    """

    def test_main_returns_zero_on_success(self):
        """
        main() возвращает 0 при успешном выполнении.
        """
        from collector import session_cleanup
        import sys
        from unittest.mock import patch, MagicMock
        
        # Мокаем SessionLocal чтобы не подключаться к реальной БД
        mock_session = MagicMock()
        
        with patch.object(session_cleanup, 'SessionLocal', return_value=mock_session):
            with patch.object(session_cleanup, 'cleanup_orphaned_sessions', return_value=(0, 0)) as mock_cleanup:
                # Вызываем main() и проверяем возвращаемое значение
                result = session_cleanup.main()
                
                # Проверяем что cleanup был вызван
                mock_cleanup.assert_called_once()
                # Проверяем что возвращаемый код 0
                assert result == 0
