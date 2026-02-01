"""
Тесты для скрипта client-disconnect.

Проверяют инварианты I5.1-I5.6:
- I5.1: Обновляет только последнюю активную сессию по CN
- I5.2: Устанавливает disconnected_at = NOW()
- I5.3: Меняет статус на 'closed'
- I5.4: Сохраняет bytes_sent/bytes_received
- I5.5: exit 0 при любой ошибке
- I5.6: Только UPDATE операции (нет INSERT)
"""

import ast
import os
import sys
from datetime import datetime, timedelta

import pytest

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from core.models import Account, Session

# Импортируем тестируемый модуль
from collector.client_disconnect import client_disconnect, get_env_vars, close_active_session


@pytest.fixture
def env():
    """
    Фикстура создает набор переменных окружения для тестов.

    Возвращает словарь с базовыми переменными окружения OpenVPN.
    """
    return {
        'common_name': 'test_user',
        'bytes_sent': '1000',
        'bytes_received': '2000',
        'time_duration': '3600'
    }


def run_client_disconnect(env_vars, db_session=None):
    """
    Вспомогательная функция для запуска client_disconnect с заданными env.

    Args:
        env_vars: словарь с переменными окружения
        db_session: опциональная сессия БД для тестирования

    Returns:
        int: код возврата функции
    """
    # Сохраняем оригинальные переменные окружения
    original_env = os.environ.copy()

    try:
        # Устанавливаем тестовые переменные окружения
        os.environ.update(env_vars)
        return client_disconnect(db_session=db_session)
    finally:
        # Восстанавливаем оригинальные переменные окружения
        os.environ.clear()
        os.environ.update(original_env)


# =============================================================================
# Тесты инвариантов I5.1-I5.4 (интеграционные)
# =============================================================================

class TestI51_UpdatesOnlyActiveSession:
    """
    Тесты для инварианта I5.1: Обновляется только последняя активная сессия по CN.
    """

    def test_disconnect_updates_only_active(self, db, env):
        """
        Тест I5.1: Обновляется только последняя активная сессия.

        Сценарий:
        1. Создаем аккаунт
        2. Создаем старую закрытую сессию
        3. Создаем новую активную сессию
        4. Вызываем client_disconnect
        5. Проверяем, что закрыта только новая сессия
        """
        # Создаем аккаунт
        account = Account(cn='user')
        db.add(account)
        db.flush()

        past = datetime.utcnow() - timedelta(hours=1)
        now = datetime.utcnow()

        # Старая закрытая сессия
        old_session = Session(
            account_id=account.id,
            connected_at=past,
            disconnected_at=past,
            source_ip='192.168.1.1',
            status='closed'
        )
        db.add(old_session)

        # Новая активная сессия
        new_session = Session(
            account_id=account.id,
            connected_at=now,
            source_ip='192.168.1.2',
            status='active'
        )
        db.add(new_session)
        db.commit()

        # Запускаем client_disconnect
        env['common_name'] = 'user'
        exit_code = run_client_disconnect(env, db_session=db)

        # Проверяем код возврата
        assert exit_code == 0

        # Обновляем объекты из БД
        db.refresh(old_session)
        db.refresh(new_session)

        # Проверяем, что старая сессия не изменилась
        assert old_session.status == 'closed'
        assert old_session.disconnected_at == past

        # Проверяем, что новая сессия закрыта
        assert new_session.status == 'closed'
        assert new_session.disconnected_at is not None

    def test_disconnect_updates_only_last_active_when_multiple(self, db, env):
        """
        Тест I5.1: При наличии нескольких активных сессий обновляется только последняя.

        Сценарий:
        1. Создаем аккаунт
        2. Создаем две активные сессии с разным временем
        3. Вызываем client_disconnect
        4. Проверяем, что закрыта только последняя по времени
        """
        # Создаем аккаунт
        account = Account(cn='user')
        db.add(account)
        db.flush()

        past = datetime.utcnow() - timedelta(hours=1)
        now = datetime.utcnow()

        # Первая (старая) активная сессия
        old_active = Session(
            account_id=account.id,
            connected_at=past,
            source_ip='192.168.1.1',
            status='active'
        )
        db.add(old_active)

        # Вторая (новая) активная сессия
        new_active = Session(
            account_id=account.id,
            connected_at=now,
            source_ip='192.168.1.2',
            status='active'
        )
        db.add(new_active)
        db.commit()

        # Запускаем client_disconnect
        env['common_name'] = 'user'
        exit_code = run_client_disconnect(env, db_session=db)

        # Проверяем код возврата
        assert exit_code == 0

        # Обновляем объекты из БД
        db.refresh(old_active)
        db.refresh(new_active)

        # Проверяем, что старая активная сессия осталась активной
        assert old_active.status == 'active'
        assert old_active.disconnected_at is None

        # Проверяем, что новая сессия закрыта
        assert new_active.status == 'closed'
        assert new_active.disconnected_at is not None


class TestI52_I53_I54_CorrectClosing:
    """
    Тесты для инвариантов I5.2, I5.3, I5.4: Корректное закрытие сессии.
    """

    def test_disconnect_closes_session_correctly(self, db, env):
        """
        Тест I5.2-I5.4: Корректное закрытие сессии.

        Сценарий:
        1. Создаем аккаунт и активную сессию
        2. Вызываем client_disconnect с конкретными bytes_sent/bytes_received
        3. Проверяем, что сессия закрыта корректно
        """
        # Создаем аккаунт
        account = Account(cn='user')
        db.add(account)
        db.flush()

        # Создаем активную сессию
        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip='192.168.1.1',
            status='active'
        )
        db.add(session)
        db.commit()

        # Запускаем client_disconnect
        env['common_name'] = 'user'
        env['bytes_sent'] = '1000'
        env['bytes_received'] = '2000'
        exit_code = run_client_disconnect(env, db_session=db)

        # Проверяем код возврата
        assert exit_code == 0

        # Обновляем объект из БД
        db.refresh(session)

        # I5.3: Проверяем статус 'closed'
        assert session.status == 'closed'

        # I5.2: Проверяем, что disconnected_at установлено
        assert session.disconnected_at is not None

        # I5.4: Проверяем статистику трафика
        assert session.bytes_sent == 1000
        assert session.bytes_received == 2000

    def test_disconnect_sets_disconnected_at_to_now(self, db, env):
        """
        Тест I5.2: disconnected_at устанавливается в текущее время.

        Сценарий:
        1. Создаем аккаунт и активную сессию
        2. Запоминаем время до вызова
        3. Вызываем client_disconnect
        4. Проверяем, что disconnected_at в пределах разумного от текущего времени
        """
        # Создаем аккаунт
        account = Account(cn='user')
        db.add(account)
        db.flush()

        # Создаем активную сессию
        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip='192.168.1.1',
            status='active'
        )
        db.add(session)
        db.commit()

        # Запоминаем время до вызова
        before_call = datetime.utcnow()

        # Запускаем client_disconnect
        env['common_name'] = 'user'
        exit_code = run_client_disconnect(env, db_session=db)

        # Запоминаем время после вызова
        after_call = datetime.utcnow()

        # Проверяем код возврата
        assert exit_code == 0

        # Обновляем объект из БД
        db.refresh(session)

        # Проверяем, что disconnected_at установлено и в правильном диапазоне
        assert session.disconnected_at is not None
        assert before_call <= session.disconnected_at <= after_call

    def test_disconnect_saves_traffic_stats(self, db, env):
        """
        Тест I5.4: Сохранение статистики трафика.

        Сценарий:
        1. Создаем аккаунт и активную сессию
        2. Вызываем client_disconnect с различными значениями bytes_sent/bytes_received
        3. Проверяем корректность сохранения
        """
        # Создаем аккаунт
        account = Account(cn='user')
        db.add(account)
        db.flush()

        # Создаем активную сессию с нулевой статистикой
        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip='192.168.1.1',
            status='active',
            bytes_sent=0,
            bytes_received=0
        )
        db.add(session)
        db.commit()

        # Тестовые значения
        test_cases = [
            {'bytes_sent': '0', 'bytes_received': '0'},
            {'bytes_sent': '999999999', 'bytes_received': '888888888'},
            {'bytes_sent': '1000000000000', 'bytes_received': '2000000000000'},
        ]

        for i, test_case in enumerate(test_cases):
            # Создаем новую сессию для каждого теста
            new_session = Session(
                account_id=account.id,
                connected_at=datetime.utcnow() + timedelta(seconds=i+1),
                source_ip='192.168.1.1',
                status='active',
                bytes_sent=0,
                bytes_received=0
            )
            db.add(new_session)
            db.commit()

            # Запускаем client_disconnect
            env['common_name'] = 'user'
            env['bytes_sent'] = test_case['bytes_sent']
            env['bytes_received'] = test_case['bytes_received']
            exit_code = run_client_disconnect(env, db_session=db)

            # Проверяем код возврата
            assert exit_code == 0

            # Обновляем объект из БД
            db.refresh(new_session)

            # I5.4: Проверяем статистику трафика
            assert new_session.bytes_sent == int(test_case['bytes_sent'])
            assert new_session.bytes_received == int(test_case['bytes_received'])


# =============================================================================
# Тесты инварианта I5.5 (fault injection)
# =============================================================================

class TestI55_ExitZeroOnError:
    """
    Тесты для инварианта I5.5: При любой ошибке скрипт возвращает exit 0.
    """

    def test_disconnect_returns_zero_on_missing_common_name(self, db, env):
        """
        Тест I5.5: При отсутствии common_name возвращается 0.
        """
        # Убираем обязательную переменную
        env.pop('common_name', None)

        exit_code = run_client_disconnect(env)

        # I5.5: Должно вернуть 0, а не падать
        assert exit_code == 0

    def test_disconnect_returns_zero_on_empty_common_name(self, db, env):
        """
        Тест I5.5: При пустом common_name возвращается 0.
        """
        env['common_name'] = ''

        exit_code = run_client_disconnect(env)

        # I5.5: Должно вернуть 0
        assert exit_code == 0

    def test_disconnect_returns_zero_on_nonexistent_account(self, db, env):
        """
        Тест I5.5: При отсутствии аккаунта возвращается 0.
        """
        # Указываем несуществующий CN
        env['common_name'] = 'nonexistent_user'

        exit_code = run_client_disconnect(env)

        # I5.5: Должно вернуть 0, не падать
        assert exit_code == 0

    def test_disconnect_returns_zero_on_no_active_session(self, db, env):
        """
        Тест I5.5: При отсутствии активной сессии возвращается 0.
        """
        # Создаем аккаунт, но без активной сессии
        account = Account(cn='user')
        db.add(account)
        db.commit()

        env['common_name'] = 'user'

        exit_code = run_client_disconnect(env)

        # I5.5: Должно вернуть 0, не падать
        assert exit_code == 0

    def test_disconnect_returns_zero_on_invalid_bytes_values(self, db, env):
        """
        Тест I5.5: При некорректных значениях bytes возвращается 0.
        """
        # Создаем аккаунт и активную сессию
        account = Account(cn='user')
        db.add(account)
        db.flush()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip='192.168.1.1',
            status='active'
        )
        db.add(session)
        db.commit()

        env['common_name'] = 'user'
        env['bytes_sent'] = 'invalid_number'
        env['bytes_received'] = 'also_invalid'

        exit_code = run_client_disconnect(env, db_session=db)

        # I5.5: Должно вернуть 0, не падать
        assert exit_code == 0

        # Проверяем, что сессия закрыта с дефолтными значениями (0)
        db.refresh(session)
        assert session.status == 'closed'
        assert session.bytes_sent == 0
        assert session.bytes_received == 0


# =============================================================================
# Тесты инварианта I5.6 (статический анализ AST)
# =============================================================================

class TestI56_NoInsertOperations:
    """
    Тесты для инварианта I5.6: Скрипт не создает новых записей (только UPDATE).

    Проверяет через AST анализ, что в коде нет вызовов db.add() или insert().
    """

    def test_no_db_add_in_source_code(self):
        """
        Тест I5.6: В исходном коде нет вызовов db.add().

        Используем AST для поиска вызовов метода add на объекте db.
        """
        # Читаем исходный код скрипта
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'client_disconnect.py'
        )

        with open(script_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # Парсим AST
        tree = ast.parse(source)

        # Ищем вызовы db.add()
        add_calls = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Проверяем вызовы вида db.add(...)
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'add':
                        # Проверяем, что это вызов на объекте с именем 'db'
                        if isinstance(node.func.value, ast.Name):
                            if node.func.value.id == 'db':
                                add_calls.append(node)

        # I5.6: Не должно быть вызовов db.add()
        assert len(add_calls) == 0, f"Found db.add() calls: {len(add_calls)}"

    def test_no_insert_calls_in_source_code(self):
        """
        Тест I5.6: В исходном коде нет вызовов insert().

        Используем AST для поиска вызовов метода insert.
        """
        # Читаем исходный код скрипта
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'client_disconnect.py'
        )

        with open(script_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # Парсим AST
        tree = ast.parse(source)

        # Ищем вызовы insert()
        insert_calls = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'insert':
                        insert_calls.append(node)
                elif isinstance(node.func, ast.Name):
                    if node.func.id == 'insert':
                        insert_calls.append(node)

        # I5.6: Не должно быть вызовов insert() (кроме sys.path.insert)
        # sys.path.insert допустим для настройки путей импорта
        non_path_inserts = []
        for node in insert_calls:
            if isinstance(node.func, ast.Attribute):
                # Проверяем, что это не sys.path.insert
                if isinstance(node.func.value, ast.Attribute):
                    if not (isinstance(node.func.value.value, ast.Name) and
                            node.func.value.value.id == 'sys' and
                            node.func.value.attr == 'path'):
                        non_path_inserts.append(node)

        assert len(non_path_inserts) == 0, f"Found insert() calls: {len(non_path_inserts)}"

    def test_only_update_operations_in_close_function(self):
        """
        Тест I5.6: Функция close_active_session только обновляет существующие записи.

        Проверяем, что в функции нет создания новых объектов Session.
        """
        # Читаем исходный код скрипта
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'client_disconnect.py'
        )

        with open(script_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # Парсим AST
        tree = ast.parse(source)

        # Ищем создание объектов Session (кроме импорта)
        session_creations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Проверяем вызовы Session(...)
                if isinstance(node.func, ast.Name):
                    if node.func.id == 'Session':
                        session_creations.append(node)

        # I5.6: Не должно быть создания новых объектов Session
        # (Session используется только для импорта и type hints)
        assert len(session_creations) == 0, f"Found Session() instantiations: {len(session_creations)}"


# =============================================================================
# Дополнительные тесты
# =============================================================================

class TestGetEnvVars:
    """
    Тесты для функции get_env_vars.
    """

    def test_get_env_vars_returns_correct_values(self, monkeypatch):
        """
        Тест: get_env_vars корректно читает переменные окружения.
        """
        # Устанавливаем переменные окружения
        monkeypatch.setenv('common_name', 'test_cn')
        monkeypatch.setenv('bytes_sent', '5000')
        monkeypatch.setenv('bytes_received', '6000')
        monkeypatch.setenv('time_duration', '7200')

        result = get_env_vars()

        assert result is not None
        assert result['common_name'] == 'test_cn'
        assert result['bytes_sent'] == 5000
        assert result['bytes_received'] == 6000
        assert result['time_duration'] == '7200'

    def test_get_env_vars_returns_none_on_missing_cn(self, monkeypatch):
        """
        Тест: get_env_vars возвращает None при отсутствии common_name.
        """
        # Убираем common_name
        monkeypatch.delenv('common_name', raising=False)

        result = get_env_vars()

        assert result is None

    def test_get_env_vars_defaults_to_zero(self, monkeypatch):
        """
        Тест: get_env_vars использует 0 по умолчанию для bytes.
        """
        monkeypatch.setenv('common_name', 'test_cn')
        monkeypatch.delenv('bytes_sent', raising=False)
        monkeypatch.delenv('bytes_received', raising=False)

        result = get_env_vars()

        assert result is not None
        assert result['bytes_sent'] == 0
        assert result['bytes_received'] == 0

    def test_get_env_vars_handles_invalid_bytes(self, monkeypatch):
        """
        Тест: get_env_vars обрабатывает некорректные значения bytes.
        """
        monkeypatch.setenv('common_name', 'test_cn')
        monkeypatch.setenv('bytes_sent', 'invalid')
        monkeypatch.setenv('bytes_received', 'also_invalid')

        result = get_env_vars()

        assert result is not None
        assert result['bytes_sent'] == 0
        assert result['bytes_received'] == 0


class TestCloseActiveSession:
    """
    Тесты для функции close_active_session.
    """

    def test_close_active_session_updates_session(self, db):
        """
        Тест: close_active_session корректно обновляет сессию.
        """
        # Создаем аккаунт и сессию
        account = Account(cn='test_user')
        db.add(account)
        db.flush()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip='192.168.1.1',
            status='active'
        )
        db.add(session)
        db.commit()

        # Закрываем сессию
        close_active_session(db, 'test_user', 1234, 5678)

        # Проверяем обновления
        db.refresh(session)
        assert session.status == 'closed'
        assert session.disconnected_at is not None
        assert session.bytes_sent == 1234
        assert session.bytes_received == 5678

    def test_close_active_session_does_nothing_when_no_active(self, db):
        """
        Тест: close_active_session ничего не делает при отсутствии активной сессии.
        """
        # Создаем аккаунт без сессий
        account = Account(cn='test_user')
        db.add(account)
        db.commit()

        # Вызываем функцию - не должно быть ошибки
        close_active_session(db, 'test_user', 100, 200)

        # Проверяем, что сессий по-прежнему нет
        sessions = db.query(Session).filter(Session.account_id == account.id).all()
        assert len(sessions) == 0

    def test_close_active_session_does_nothing_on_wrong_cn(self, db):
        """
        Тест: close_active_session ничего не делает при неверном CN.
        """
        # Создаем аккаунт и сессию
        account = Account(cn='correct_user')
        db.add(account)
        db.flush()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip='192.168.1.1',
            status='active'
        )
        db.add(session)
        db.commit()

        # Вызываем функцию с неверным CN
        close_active_session(db, 'wrong_user', 100, 200)

        # Проверяем, что сессия не изменилась
        db.refresh(session)
        assert session.status == 'active'
        assert session.disconnected_at is None
