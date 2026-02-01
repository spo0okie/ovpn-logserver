"""
Тесты для проверки инвариантов схемы базы данных.

Этот модуль содержит тесты для проверки:
- I1.1: Уникальность CN в таблице accounts
- I1.2: Каскадное удаление сессий при удалении аккаунта
- I1.3: Ограничение ENUM для статуса сессий
- I1.4: NOT NULL для connected_at
- I1.5: Воспроизводимость миграций
"""

import os
import subprocess
import pytest
import pymysql
from typing import Generator


# Конфигурация подключения к тестовой БД
TEST_DB_CONFIG = {
    'host': os.environ.get('TEST_DB_HOST', 'localhost'),
    'port': int(os.environ.get('TEST_DB_PORT', '3306')),
    'user': os.environ.get('TEST_DB_USER', 'openvpn_user'),
    'password': os.environ.get('TEST_DB_PASSWORD', 'openvpn_password'),
    'database': os.environ.get('TEST_DB_NAME', 'openvpn_logs_test'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': False
}


@pytest.fixture(scope='module')
def db_connection() -> Generator[pymysql.Connection, None, None]:
    """
    Фикстура для создания соединения с тестовой БД.

    Создаёт соединение которое используется для всех тестов в модуле.
    После завершения тестов соединение закрывается.
    """
    conn = pymysql.connect(**TEST_DB_CONFIG)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_tables(db_connection: pymysql.Connection) -> Generator[None, None, None]:
    """
    Фикстура для очистки таблиц перед каждым тестом.

    Удаляет все данные из таблиц в правильном порядке (сначала дочерние),
    чтобы каждый тест начинался с чистого состояния.
    """
    cursor = db_connection.cursor()
    try:
        # Очищаем таблицы в обратном порядке (сначала дочерние)
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("TRUNCATE TABLE geoip_cache")
        cursor.execute("TRUNCATE TABLE connection_attempts")
        cursor.execute("TRUNCATE TABLE sessions")
        cursor.execute("TRUNCATE TABLE accounts")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        db_connection.commit()
    except Exception as e:
        db_connection.rollback()
        raise e
    finally:
        cursor.close()

    yield


class TestInvariantI11:
    """
    Тесты для инварианта I1.1: Уникальность CN в таблице accounts.

    Проверяет что поле cn в таблице accounts имеет уникальный индекс
    и попытка вставки дубликата вызывает ошибку.
    """

    def test_unique_cn_constraint(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.1: Попытка вставить дубликат CN должна падать с DUPLICATE KEY ERROR.

        Сценарий:
        1. Вставляем запись с CN='test'
        2. Пытаемся вставить ещё одну запись с тем же CN
        3. Ожидаем ошибку IntegrityError (1062 - Duplicate entry)
        """
        cursor = db_connection.cursor()

        # Шаг 1: Вставляем первую запись
        cursor.execute("INSERT INTO accounts (cn) VALUES ('test')")
        db_connection.commit()

        # Шаг 2: Пытаемся вставить дубликат
        with pytest.raises(pymysql.err.IntegrityError) as exc_info:
            cursor.execute("INSERT INTO accounts (cn) VALUES ('test')")
            db_connection.commit()

        # Шаг 3: Проверяем что ошибка связана с дубликатом ключа
        assert exc_info.value.args[0] == 1062  # Код ошибки Duplicate entry
        assert 'Duplicate entry' in str(exc_info.value)

        cursor.close()

    def test_unique_cn_different_values_allowed(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.1 (дополнительный): Разные CN должны вставляться без проблем.

        Сценарий:
        1. Вставляем несколько записей с разными CN
        2. Проверяем что все записи успешно добавлены
        """
        cursor = db_connection.cursor()

        cursor.execute("INSERT INTO accounts (cn) VALUES ('user1')")
        cursor.execute("INSERT INTO accounts (cn) VALUES ('user2')")
        cursor.execute("INSERT INTO accounts (cn) VALUES ('user3')")
        db_connection.commit()

        cursor.execute("SELECT COUNT(*) as cnt FROM accounts")
        result = cursor.fetchone()
        assert result['cnt'] == 3

        cursor.close()


class TestInvariantI12:
    """
    Тесты для инварианта I1.2: Каскадное удаление сессий при удалении аккаунта.

    Проверяет что внешний ключ account_id в таблице sessions
    настроен с ON DELETE CASCADE.
    """

    def test_cascade_delete_sessions(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.2: Удаление account каскадно удаляет сессии.

        Сценарий:
        1. Создаём аккаунт
        2. Создаём сессию для этого аккаунта
        3. Удаляем аккаунт
        4. Проверяем что сессия также удалена
        """
        cursor = db_connection.cursor()

        # Шаг 1: Создаём аккаунт
        cursor.execute("INSERT INTO accounts (cn) VALUES ('test_user')")
        account_id = cursor.lastrowid
        db_connection.commit()

        # Шаг 2: Создаём сессию
        cursor.execute(
            "INSERT INTO sessions (account_id, connected_at, source_ip) VALUES (%s, NOW(), '192.168.1.1')",
            (account_id,)
        )
        session_id = cursor.lastrowid
        db_connection.commit()

        # Проверяем что сессия создана
        cursor.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
        assert cursor.fetchone() is not None

        # Шаг 3: Удаляем аккаунт
        cursor.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
        db_connection.commit()

        # Шаг 4: Проверяем что сессия удалена (ожидаем 0 строк)
        cursor.execute("SELECT COUNT(*) as cnt FROM sessions WHERE account_id = %s", (account_id,))
        result = cursor.fetchone()
        assert result['cnt'] == 0

        cursor.close()

    def test_cascade_delete_multiple_sessions(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.2 (дополнительный): Удаление аккаунта удаляет все его сессии.

        Сценарий:
        1. Создаём аккаунт
        2. Создаём несколько сессий для этого аккаунта
        3. Удаляем аккаунт
        4. Проверяем что все сессии удалены
        """
        cursor = db_connection.cursor()

        cursor.execute("INSERT INTO accounts (cn) VALUES ('multi_session_user')")
        account_id = cursor.lastrowid
        db_connection.commit()

        # Создаём 3 сессии
        for i in range(3):
            cursor.execute(
                "INSERT INTO sessions (account_id, connected_at, source_ip) VALUES (%s, NOW(), %s)",
                (account_id, f'192.168.1.{i+1}')
            )
        db_connection.commit()

        # Проверяем что сессии созданы
        cursor.execute("SELECT COUNT(*) as cnt FROM sessions WHERE account_id = %s", (account_id,))
        assert cursor.fetchone()['cnt'] == 3

        # Удаляем аккаунт
        cursor.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
        db_connection.commit()

        # Проверяем что все сессии удалены
        cursor.execute("SELECT COUNT(*) as cnt FROM sessions WHERE account_id = %s", (account_id,))
        assert cursor.fetchone()['cnt'] == 0

        cursor.close()


class TestInvariantI13:
    """
    Тесты для инварианта I1.3: Ограничение ENUM для статуса сессий.

    Проверяет что поле status в таблице sessions ограничено
    значениями ENUM('active', 'closed', 'error').
    """

    def test_valid_status_values(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.3: Валидные значения статуса должны приниматься.

        Сценарий:
        1. Создаём аккаунт
        2. Вставляем сессии со всеми валидными статусами
        3. Проверяем что все вставки успешны
        """
        cursor = db_connection.cursor()

        cursor.execute("INSERT INTO accounts (cn) VALUES ('status_test')")
        account_id = cursor.lastrowid
        db_connection.commit()

        valid_statuses = ['active', 'closed', 'error']

        for status in valid_statuses:
            cursor.execute(
                "INSERT INTO sessions (account_id, connected_at, source_ip, status) VALUES (%s, NOW(), '192.168.1.1', %s)",
                (account_id, status)
            )
        db_connection.commit()

        cursor.execute("SELECT COUNT(*) as cnt FROM sessions WHERE account_id = %s", (account_id,))
        assert cursor.fetchone()['cnt'] == len(valid_statuses)

        cursor.close()

    def test_invalid_status_rejected(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.3: Невалидный статус должен отклоняться.

        Сценарий:
        1. Создаём аккаунт
        2. Пытаемся вставить сессию с невалидным статусом
        3. Ожидаем ошибку DataError (1265 - Data truncated for column)
        """
        cursor = db_connection.cursor()

        cursor.execute("INSERT INTO accounts (cn) VALUES ('invalid_status_test')")
        account_id = cursor.lastrowid
        db_connection.commit()

        with pytest.raises(pymysql.err.DataError) as exc_info:
            cursor.execute(
                "INSERT INTO sessions (account_id, connected_at, source_ip, status) VALUES (%s, NOW(), '192.168.1.1', 'invalid')",
                (account_id,)
            )
            db_connection.commit()

        # Проверяем что ошибка связана с невалидным значением ENUM
        # MySQL может возвращать разные коды ошибок для ENUM
        error_msg = str(exc_info.value).lower()
        assert any(
            phrase in error_msg
            for phrase in ['data truncated', 'incorrect', 'invalid']
        )

        cursor.close()


class TestInvariantI14:
    """
    Тесты для инварианта I1.4: NOT NULL для connected_at.

    Проверяет что поле connected_at в таблице sessions
    имеет ограничение NOT NULL.
    """

    def test_null_connected_at_rejected(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.4: NULL в connected_at должен отклоняться.

        Сценарий:
        1. Создаём аккаунт
        2. Пытаемся вставить сессию с connected_at = NULL
        3. Ожидаем ошибку IntegrityError (1048 - Column cannot be null)
        """
        cursor = db_connection.cursor()

        cursor.execute("INSERT INTO accounts (cn) VALUES ('null_time_test')")
        account_id = cursor.lastrowid
        db_connection.commit()

        with pytest.raises(pymysql.err.IntegrityError) as exc_info:
            cursor.execute(
                "INSERT INTO sessions (account_id, connected_at, source_ip) VALUES (%s, NULL, '192.168.1.1')",
                (account_id,)
            )
            db_connection.commit()

        # Проверяем что ошибка связана с NULL значением
        assert exc_info.value.args[0] == 1048  # Код ошибки Column cannot be null
        assert 'cannot be null' in str(exc_info.value).lower()

        cursor.close()

    def test_valid_connected_at_accepted(self, db_connection: pymysql.Connection) -> None:
        """
        Тест I1.4 (дополнительный): Валидное значение connected_at должно приниматься.

        Сценарий:
        1. Создаём аккаунт
        2. Вставляем сессию с валидным connected_at
        3. Проверяем что вставка успешна
        """
        cursor = db_connection.cursor()

        cursor.execute("INSERT INTO accounts (cn) VALUES ('valid_time_test')")
        account_id = cursor.lastrowid
        db_connection.commit()

        cursor.execute(
            "INSERT INTO sessions (account_id, connected_at, source_ip) VALUES (%s, NOW(), '192.168.1.1')",
            (account_id,)
        )
        db_connection.commit()

        cursor.execute("SELECT * FROM sessions WHERE account_id = %s", (account_id,))
        result = cursor.fetchone()
        assert result is not None
        assert result['connected_at'] is not None

        cursor.close()


class TestInvariantI15:
    """
    Тесты для инварианта I1.5: Воспроизводимость миграций.

    Проверяет что миграции можно применить, откатить и снова применить
    без ошибок.
    """

    def test_migration_reproducibility(self) -> None:
        """
        Тест I1.5: Миграции должны быть воспроизводимы.

        Сценарий:
        1. Откатываем все миграции (downgrade base)
        2. Применяем миграции (upgrade head)
        3. Проверяем что все таблицы созданы
        4. Снова откатываем и применяем
        5. Проверяем что всё работает корректно
        """
        # Получаем путь к alembic.ini
        alembic_ini_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'alembic.ini'
        )

        # Функция для выполнения alembic команд
        def run_alembic_command(command: list[str]) -> subprocess.CompletedProcess:
            """Выполняет команду alembic и возвращает результат."""
            full_command = ['alembic', '-c', alembic_ini_path] + command
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )
            return result

        # Шаг 1: Откатываем все миграции
        result = run_alembic_command(['downgrade', 'base'])
        # Игнорируем ошибки если база уже пустая

        # Шаг 2: Применяем миграции
        result = run_alembic_command(['upgrade', 'head'])
        assert result.returncode == 0, f"Upgrade failed: {result.stderr}"

        # Шаг 3: Проверяем что таблицы созданы
        conn = pymysql.connect(**TEST_DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            AND TABLE_NAME IN ('accounts', 'sessions', 'connection_attempts', 'geoip_cache')
        """, (TEST_DB_CONFIG['database'],))

        tables = [row['TABLE_NAME'] for row in cursor.fetchall()]
        expected_tables = {'accounts', 'sessions', 'connection_attempts', 'geoip_cache'}
        assert set(tables) == expected_tables, f"Missing tables: {expected_tables - set(tables)}"

        cursor.close()
        conn.close()

        # Шаг 4: Откатываем и снова применяем
        result = run_alembic_command(['downgrade', 'base'])
        assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

        result = run_alembic_command(['upgrade', 'head'])
        assert result.returncode == 0, f"Second upgrade failed: {result.stderr}"

        # Шаг 5: Проверяем что таблицы снова созданы
        conn = pymysql.connect(**TEST_DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            AND TABLE_NAME IN ('accounts', 'sessions', 'connection_attempts', 'geoip_cache')
        """, (TEST_DB_CONFIG['database'],))

        tables = [row['TABLE_NAME'] for row in cursor.fetchall()]
        assert set(tables) == expected_tables

        cursor.close()
        conn.close()

    def test_migration_version_tracking(self) -> None:
        """
        Тест I1.5 (дополнительный): Проверка версионирования миграций.

        Проверяет что Alembic корректно отслеживает версии миграций.
        """
        alembic_ini_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'alembic.ini'
        )

        result = subprocess.run(
            ['alembic', '-c', alembic_ini_path, 'current'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )

        # Проверяем что команда выполнилась успешно
        assert result.returncode == 0, f"Failed to get current version: {result.stderr}"

        # Проверяем что текущая версия - '001'
        assert '001' in result.stdout, f"Expected version 001, got: {result.stdout}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
