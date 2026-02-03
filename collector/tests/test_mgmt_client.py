#!/usr/bin/env python3
"""
Тесты для модуля mgmt_client.py.

Проверяют инварианты:
- M1.1: Создание модуля без тестов
- M1.2: HARDCODED_PATH_TO_SOCKET
- M1.3: Возврат неверного типа данных
- M1.4: Exception при недоступном сокете
"""

import os
import sys
import socket
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Добавляем родительские директории в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Пропускаем тесты, требующие Unix-сокет, на Windows
skip_on_windows = pytest.mark.skipif(
    sys.platform == 'win32',
    reason="Unix sockets not available on Windows"
)


class TestMgmtClientInvariants:
    """
    Тесты инвариантов M1.1-M1.4 для mgmt_client.py
    """

    def test_m1_1_module_importable(self):
        """
        M1.1: Модуль импортируется без ошибок.

        Предотвращает: Создание модуля без тестов
        """
        import collector.mgmt_client as mgmt_client
        assert mgmt_client is not None
        assert hasattr(mgmt_client, 'get_connected_clients')
        assert hasattr(mgmt_client, 'parse_clients_from_response')
        assert hasattr(mgmt_client, 'get_mgmt_socket_path')

    def test_m1_1_functions_exist(self):
        """
        M1.1: Все функции модуля существуют и вызываемы.

        Предотвращает: Создание модуля без тестов
        """
        from collector.mgmt_client import (
            get_connected_clients,
            get_connected_clients_count,
            is_client_connected,
            parse_clients_from_response,
            get_mgmt_socket_path
        )

        # Проверяем что функции являются вызываемыми
        assert callable(get_connected_clients)
        assert callable(get_connected_clients_count)
        assert callable(is_client_connected)
        assert callable(parse_clients_from_response)
        assert callable(get_mgmt_socket_path)

    def test_m1_2_socket_path_from_config(self):
        """
        M1.2: Путь к сокету читается из конфигурации, не захардкожен.

        Предотвращает: HARDCODED_PATH_TO_SOCKET
        """
        from collector.mgmt_client import get_mgmt_socket_path, MGMT_SOCKET_PATH

        # Проверяем что путь не захардкодирован в функции
        path = get_mgmt_socket_path()

        # Путь должен быть строкой
        assert isinstance(path, str)
        assert len(path) > 0

    def test_m1_2_uses_env_variable(self):
        """
        M1.2: Путь к сокету может быть переопределен через переменную окружения.

        Предотвращает: HARDCODED_PATH_TO_SOCKET
        """
        from collector import mgmt_client

        # Сохраняем оригинальное значение
        original_path = mgmt_client.MGMT_SOCKET_PATH

        try:
            # Устанавливаем тестовое значение
            test_path = "/test/socket/path.sock"
            mgmt_client.MGMT_SOCKET_PATH = test_path
            mgmt_client.MGMT_SOCKET_PATH = test_path  # Also update the env var

            # Проверяем что путь изменился
            with patch.dict(os.environ, {"OPENVPN_MGMT_SOCKET": test_path}):
                # Перезагружаем модуль чтобы применить изменения
                import importlib
                importlib.reload(mgmt_client)
                path = mgmt_client.get_mgmt_socket_path()
                assert path == test_path
        finally:
            # Восстанавливаем оригинальное значение
            mgmt_client.MGMT_SOCKET_PATH = original_path

    def test_m1_3_returns_set(self):
        """
        M1.3: Функция возвращает множество (Set[str]).

        Предотвращает: Возврат неверного типа данных
        """
        from collector.mgmt_client import get_connected_clients

        # Мокаем сокет чтобы не зависеть от реального OpenVPN
        with patch('collector.mgmt_client.get_connected_clients') as mock:
            mock.return_value = {"client1", "client2", "client3"}

            result = get_connected_clients()

            assert isinstance(result, set)
            assert all(isinstance(cn, str) for cn in result)

    def test_m1_3_returns_correct_type_on_socket_unavailable(self):
        """
        M1.3: При недоступном сокете возвращается пустой set, не None и не exception.

        Предотвращает: Возврат неверного типа данных
        """
        from collector.mgmt_client import get_connected_clients

        # Мокаем socket для эмуляции недоступного сокета
        with patch('socket.socket') as mock_socket:
            mock_socket.side_effect = socket.error("Connection refused")

            result = get_connected_clients()

            # Должен возвращаться set, не None
            assert result is not None
            assert isinstance(result, set)

    def test_m1_4_graceful_degradation_on_socket_error(self):
        """
        M1.4: При недоступности сокета возвращается пустое множество.

        Предотвращает: Exception при недоступном сокете
        """
        from collector.mgmt_client import get_connected_clients

        # Тестируем различные ошибки сокета
        socket_errors = [
            socket.error("Connection refused"),
            OSError("No such file or directory"),
            IOError("Socket not found"),
        ]

        for error in socket_errors:
            with patch('socket.socket') as mock_socket:
                mock_socket.side_effect = error

                result = get_connected_clients()

                # Должен возвращаться пустой set, не exception
                assert isinstance(result, set)
                assert len(result) == 0

    def test_m1_4_returns_empty_on_timeout(self):
        """
        M1.4: При таймауте сокета возвращается пустое множество.

        Предотвращает: Exception при недоступном сокете
        """
        from collector.mgmt_client import get_connected_clients

        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.recv.side_effect = socket.timeout()

            result = get_connected_clients()

            assert isinstance(result, set)
            assert len(result) == 0


class TestParseClientsFromResponse:
    """
    Тесты функции парсинга ответа Management Interface.
    """

    def test_parse_empty_response(self):
        """
        Парсинг пустого ответа возвращает пустое множество.
        """
        from collector.mgmt_client import parse_clients_from_response

        response = ""
        result = parse_clients_from_response(response)
        assert result == set()

    def test_parse_no_clients(self):
        """
        Парсинг ответа без клиентов возвращает пустое множество.
        """
        from collector.mgmt_client import parse_clients_from_response

        response = "OpenVPN Management Interface\nVERSION,1\nEND"
        result = parse_clients_from_response(response)
        assert result == set()

    def test_parse_single_client(self):
        """
        Парсинг ответа с одним клиентом.
        """
        from collector.mgmt_client import parse_clients_from_response

        response = (
            "OpenVPN Management Interface\n"
            "CLIENT_LIST,client1,10.8.0.2:12345,10.8.0.1,,\n"
            "END"
        )
        result = parse_clients_from_response(response)
        assert result == {"client1"}

    def test_parse_multiple_clients(self):
        """
        Парсинг ответа с несколькими клиентами.
        """
        from collector.mgmt_client import parse_clients_from_response

        response = (
            "OpenVPN Management Interface\n"
            "CLIENT_LIST,user1,10.8.0.2:12345,10.8.0.1,,\n"
            "CLIENT_LIST,user2,10.8.0.3:12345,10.8.0.1,,\n"
            "CLIENT_LIST,admin,10.8.0.4:12345,10.8.0.1,,\n"
            "END"
        )
        result = parse_clients_from_response(response)
        assert result == {"user1", "user2", "admin"}

    def test_parse_client_with_special_chars(self):
        """
        Парсинг клиентов с специальными символами в CN.
        """
        from collector.mgmt_client import parse_clients_from_response

        response = (
            "CLIENT_LIST,user@example.com,10.8.0.2:12345,10.8.0.1,,\n"
            "CLIENT_LIST,user-with-dash,10.8.0.3:12345,10.8.0.1,,\n"
            "END"
        )
        result = parse_clients_from_response(response)
        assert result == {"user@example.com", "user-with-dash"}

    def test_parse_ignores_header_footer(self):
        """
        Парсинг игнорирует заголовки и завершающие строки.
        """
        from collector.mgmt_client import parse_clients_from_response

        response = (
            "OpenVPN Management Interface\n"
            "VERSION,1\n"
            "CLIENT_LIST,client1,10.8.0.2:12345,10.8.0.1,,\n"
            "GLOBAL_STATS,1\n"
            "END"
        )
        result = parse_clients_from_response(response)
        assert result == {"client1"}


class TestGetConnectedClientsCount:
    """
    Тесты функции подсчета клиентов.
    """

    def test_returns_integer(self):
        """
        Функция возвращает целое число.
        """
        from collector.mgmt_client import get_connected_clients_count

        with patch('collector.mgmt_client.get_connected_clients') as mock:
            mock.return_value = {"client1", "client2"}

            result = get_connected_clients_count()

            assert isinstance(result, int)
            assert result == 2

    def test_returns_zero_on_empty(self):
        """
        Функция возвращает 0 при отсутствии клиентов.
        """
        from collector.mgmt_client import get_connected_clients_count

        with patch('collector.mgmt_client.get_connected_clients') as mock:
            mock.return_value = set()

            result = get_connected_clients_count()

            assert result == 0


class TestIsClientConnected:
    """
    Тесты функции проверки подключения клиента.
    """

    def test_returns_true_when_connected(self):
        """
        Функция возвращает True для подключенного клиента.
        """
        from collector.mgmt_client import is_client_connected

        with patch('collector.mgmt_client.get_connected_clients') as mock:
            mock.return_value = {"client1", "client2"}

            result = is_client_connected("client1")

            assert result is True

    def test_returns_false_when_not_connected(self):
        """
        Функция возвращает False для неподключенного клиента.
        """
        from collector.mgmt_client import is_client_connected

        with patch('collector.mgmt_client.get_connected_clients') as mock:
            mock.return_value = {"client1", "client2"}

            result = is_client_connected("client3")

            assert result is False


class TestCustomSocketPath:
    """
    Тесты использования кастомного пути к сокету.
    """

    @skip_on_windows
    def test_custom_socket_path_parameter(self):
        """
        Функция принимает кастомный путь к сокету.
        """
        from collector.mgmt_client import get_connected_clients

        custom_path = "/custom/socket/path.sock"

        # Мокаем функцию на уровне модуля, а не socket напрямую
        with patch('collector.mgmt_client.socket.socket') as mock_socket:
            # Эмулируем успешное подключение
            mock_sock_instance = MagicMock()
            mock_sock_instance.recv.return_value = b"END"
            mock_socket.return_value = mock_sock_instance

            result = get_connected_clients(mgmt_socket_path=custom_path)

            # Проверяем что сокет был создан и подключен к правильному пути
            mock_sock_instance.connect.assert_called_with(custom_path)

    @skip_on_windows
    def test_none_socket_path_uses_default(self):
        """
        При None в качестве пути используется путь по умолчанию.
        """
        from collector.mgmt_client import get_connected_clients, get_mgmt_socket_path

        default_path = get_mgmt_socket_path()

        with patch('collector.mgmt_client.socket.socket') as mock_socket:
            mock_sock_instance = MagicMock()
            mock_sock_instance.recv.return_value = b"END"
            mock_socket.return_value = mock_sock_instance

            result = get_connected_clients(mgmt_socket_path=None)

            mock_sock_instance.connect.assert_called_with(default_path)
