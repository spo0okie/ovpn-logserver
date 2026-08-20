#!/usr/bin/env python3
"""
E2E тесты для проверки полного цикла работы с orphaned сессиями в Docker.

Тесты инвариантов:
- E6.1: Docker Compose поднимает все сервисы
- E6.2: OpenVPN сервер запускается с Management Interface
- E6.3: При подключении клиента создается сессия в БД
- E6.4: При отключении клиента сессия закрывается
- E6.5: При реконнекте старая orphaned сессия закрывается
- E6.6: sync_all.py вызывает session_cleanup

Все тесты требуют запущенного Docker Compose окружения.
"""

import os
import sys
import pytest
import subprocess
import time
import socket
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def wait_for_port(host: str, port: int, timeout: int = 60) -> bool:
    """
    Ожидает доступности порта.
    
    Args:
        host: Хост для проверки
        port: Порт для проверки
        timeout: Максимальное время ожидания в секундах
    
    Returns:
        True если порт доступен, False если таймаут
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except socket.error:
            pass
        time.sleep(1)
    return False


def run_docker_compose_cmd(cmd: list, cwd: str = None) -> subprocess.CompletedProcess:
    """
    Запускает команду docker-compose.
    
    Args:
        cmd: Команда для выполнения
        cwd: Рабочая директория
    
    Returns:
        Результат выполнения команды
    """
    full_cmd = ["docker-compose", "-f", "docker/docker-compose.yml"] + cmd
    return subprocess.run(full_cmd, cwd=cwd or os.getcwd(), capture_output=True, text=True)


def mysql_query(sql: str) -> subprocess.CompletedProcess:
    """
    Выполняет SQL в контейнере MySQL.

    Учётные данные берутся из окружения (как их задаёт docker-compose), а не
    хардкодятся: раньше в тестах стояли -uopenvpn -popenvpn_password, из-за чего
    смена MYSQL_USER/MYSQL_PASSWORD в .env ломала тесты.
    Пароль передаётся через MYSQL_PWD, чтобы не светиться в списке процессов.
    """
    user = os.environ.get("MYSQL_USER", "openvpn")
    password = os.environ.get("MYSQL_PASSWORD", "openvpn_password")
    database = os.environ.get("MYSQL_DATABASE", "openvpn_logs")
    return subprocess.run(
        ["docker", "exec", "-e", f"MYSQL_PWD={password}", "openvpn-mysql",
         "mysql", f"-u{user}", database, "-e", sql],
        capture_output=True, text=True,
    )


def run_in_container_with_env(container: str, script: str, env: dict) -> subprocess.CompletedProcess:
    """
    Запускает скрипт внутри контейнера с передачей переменных окружения.
    
    Args:
        container: Имя контейнера
        script: Путь к скрипту внутри контейнера
        env: Словарь переменных окружения
    
    Returns:
        Результат выполнения команды
    """
    # Формируем команду docker exec с переменными окружения (-e)
    cmd = ["docker", "exec"]
    for key, value in env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([container, "python", script])
    
    return subprocess.run(cmd, capture_output=True, text=True)


class TestDockerComposeServices:
    """
    Тесты для проверки Docker Compose сервисов (E6.1).
    """

    @pytest.fixture(scope="class")
    def docker_compose_up(self):
        """
        Поднимает Docker Compose окружение.
        """
        result = run_docker_compose_cmd(["up", "-d"])
        yield result
        # После завершения тестов останавливаем окружение
        run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_e6_1_mysql_container_running(self, docker_compose_up):
        """
        E6.1: MySQL контейнер запущен и работает.
        """
        # Проверяем что mysql контейнер запущен
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True
        )
        assert "openvpn-mysql" in result.stdout, "MySQL container should be running"
        
    def test_e6_1_openvpn_container_running(self, docker_compose_up):
        """
        E6.1: OpenVPN контейнер запущен и работает.
        """
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True
        )
        assert "openvpn-server" in result.stdout, "OpenVPN container should be running"

    def test_e6_1_web_container_running(self, docker_compose_up):
        """
        E6.1: Web контейнер запущен и работает.
        """
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True
        )
        assert "openvpn-web" in result.stdout, "Web container should be running"


class TestManagementInterface:
    """
    Тесты для проверки Management Interface (E6.2).
    """

    @pytest.fixture(scope="class")
    def docker_compose_up(self):
        """
        Поднимает Docker Compose окружение.
        """
        result = run_docker_compose_cmd(["up", "-d"])
        yield result
        run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_e6_2_management_socket_exists(self, docker_compose_up):
        """
        E6.2: Management socket файл существует в контейнере OpenVPN.
        """
        # Проверяем что сокет файл существует
        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "ls", "-la", "/run/openvpn/"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "Command should succeed"
        assert "mgmt.sock" in result.stdout or "mgmt" in result.stdout, \
            "Management socket should exist"

    def test_e6_2_management_socket_accessible(self, docker_compose_up):
        """
        E6.2: Management socket доступен для чтения.
        """
        # Проверяем права доступа к сокету
        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "test", "-S", "/run/openvpn/mgmt.sock"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "Management socket should be accessible"


class TestSessionLifecycle:
    """
    Тесты для проверки жизненного цикла сессии (E6.3, E6.4, E6.5).
    """

    @pytest.fixture(scope="class")
    def docker_compose_up(self):
        """
        Поднимает Docker Compose окружение и ожидает готовности MySQL.
        """
        run_docker_compose_cmd(["up", "-d"])
        # Ждем готовности MySQL
        wait_for_port("localhost", 3306, timeout=60)
        yield
        run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_e6_3_session_created_on_connect(self, docker_compose_up):
        """
        E6.3: При подключении клиента создается сессия в БД.
        """
        # Запускаем client_connect скрипт с тестовыми переменными окружения
        env = {
            "common_name": "test_client_e2e",
            "trusted_ip": "192.168.100.100",
            "tls_serial_0": "e2e_test_serial",
            "trusted_port": "12345",
            "ifconfig_pool_remote_ip": "10.8.0.100",
            "time_unix": str(int(datetime.utcnow().timestamp()))
        }

        result = run_in_container_with_env("openvpn-server", "/app/collector/client_connect.py", env)
        
        # Скрипт должен вернуть 0 (не блокировать VPN)
        assert result.returncode == 0, f"client_connect should return 0: {result.stderr}"
        
        # Проверяем что сессия создана в БД (JOIN с accounts для поиска по cn)
        db_result = mysql_query("SELECT COUNT(*) FROM sessions s JOIN accounts a ON s.account_id=a.id WHERE a.cn='test_client_e2e'")
        assert "1" in db_result.stdout or "2" in db_result.stdout, "Session should be created in database"

    def test_e6_4_session_closed_on_disconnect(self, docker_compose_up):
        """
        E6.4: При отключении клиента сессия закрывается.
        """
        # Сначала создаем сессию
        env = {
            "common_name": "test_disconnect_e2e",
            "trusted_ip": "192.168.100.101",
            "tls_serial_0": "disconnect_test_serial"
        }
        
        run_in_container_with_env("openvpn-server", "/app/collector/client_connect.py", env)
        
        # Запускаем client_disconnect скрипт
        env["connected_at"] = str(int(datetime.utcnow().timestamp()))
        
        result = run_in_container_with_env("openvpn-server", "/app/collector/client_disconnect.py", env)
        
        assert result.returncode == 0, f"client_disconnect should return 0: {result.stderr}"
        
        # Проверяем что сессия закрыта (JOIN с accounts для поиска по cn)
        db_result = mysql_query("SELECT s.status FROM sessions s JOIN accounts a ON s.account_id=a.id WHERE a.cn='test_disconnect_e2e' ORDER BY s.id DESC LIMIT 1")
        assert "closed" in db_result.stdout, "Session should be closed"

    def test_e6_5_orphaned_session_on_reconnect(self, docker_compose_up):
        """
        E6.5: При реконнекте старая orphaned сессия закрывается, создается новая.
        """
        # Сначала создаем сессию
        env = {
            "common_name": "test_reconnect_e2e",
            "trusted_ip": "192.168.100.102",
            "tls_serial_0": "reconnect_test_serial"
        }
        
        run_in_container_with_env("openvpn-server", "/app/collector/client_connect.py", env)
        
        # Проверяем что есть активная сессия (JOIN с accounts для поиска по cn)
        check_result = mysql_query("SELECT COUNT(*) FROM sessions s JOIN accounts a ON s.account_id=a.id WHERE a.cn='test_reconnect_e2e' AND s.status='active'")
        initial_count = int(check_result.stdout.strip().split('\n')[-1])
        assert initial_count >= 1, "Should have at least one active session"
        
        # Имитируем реконнект - вызываем client_connect снова
        env["trusted_ip"] = "192.168.100.103"  # Новый IP
        
        result = run_in_container_with_env("openvpn-server", "/app/collector/client_connect.py", env)
        
        assert result.returncode == 0, f"client_connect should return 0: {result.stderr}"
        
        # Проверяем что старая сессия помечена как error (JOIN с accounts для поиска по cn)
        orphan_result = mysql_query("SELECT COUNT(*) FROM sessions s JOIN accounts a ON s.account_id=a.id WHERE a.cn='test_reconnect_e2e' AND s.status='error'")
        assert "1" in orphan_result.stdout, "Old session should be marked as error (orphaned)"
        
        # Проверяем что создана новая активная сессия (JOIN с accounts для поиска по cn)
        new_result = mysql_query("SELECT COUNT(*) FROM sessions s JOIN accounts a ON s.account_id=a.id WHERE a.cn='test_reconnect_e2e' AND s.status='active' AND s.source_ip='192.168.100.103'")
        assert "1" in new_result.stdout, "New session should be created with new IP"


class TestSyncAllSessionCleanup:
    """
    Тесты для проверки sync_all с session_cleanup (E6.6).
    """

    @pytest.fixture(scope="class")
    def docker_compose_up(self):
        """
        Поднимает Docker Compose окружение и ожидает готовности всех сервисов.
        """
        run_docker_compose_cmd(["up", "-d"])
        wait_for_port("localhost", 3306, timeout=60)
        wait_for_port("localhost", 8000, timeout=60)
        yield
        run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_e6_6_sync_all_runs_successfully(self, docker_compose_up):
        """
        E6.6: sync_all.py запускается и выполняет очистку сессий.
        """
        # Создаем тестовые данные - сессию в БД
        env = {
            "common_name": "test_sync_e2e",
            "trusted_ip": "192.168.100.104",
            "tls_serial_0": "sync_test_serial"
        }
        
        run_in_container_with_env("openvpn-server", "/app/collector/client_connect.py", env)
        
        # Запускаем sync_all.py
        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "python", "/app/collector/sync_all.py"],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        assert result.returncode == 0, f"sync_all should return 0: {result.stderr}"
        assert "session cleanup" in result.stdout.lower() or "sync_all.py" in result.stderr.lower(), \
            "sync_all should mention session cleanup"

    def test_session_cleanup_is_fail_closed_without_clients(self, docker_compose_up):
        """
        C1.7: при отсутствии подключённых клиентов cleanup НИЧЕГО не трогает.

        Пустой ответ Management Interface не означает «никто не подключён» —
        сокет мог быть недоступен или перезапущен. Если бы cleanup доверял
        такому ответу, он разом пометил бы error все живые сессии.

        Раньше этот тест утверждал обратное (ждал, что сессия станет error) и
        противоречил инварианту, зафиксированному в коде.
        """
        mysql_query(
            "INSERT INTO accounts (cn, serial_number, created_at, updated_at) "
            "VALUES ('test_direct_cleanup', 'direct_test_serial', NOW(), NOW())"
        )
        get_id = mysql_query("SELECT id FROM accounts WHERE cn='test_direct_cleanup'")
        account_id = get_id.stdout.strip().splitlines()[-1]

        # «Зависшая» активная сессия старше snapshot_time
        mysql_query(
            "INSERT INTO sessions (account_id, connected_at, source_ip, status) "
            f"VALUES ({account_id}, DATE_SUB(NOW(), INTERVAL 2 HOUR), "
            "'192.168.100.200', 'active')"
        )

        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "python", "/app/collector/session_cleanup.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"session_cleanup должен вернуть 0: {result.stderr}"

        check = mysql_query(f"SELECT status FROM sessions WHERE account_id={account_id}")
        assert "active" in check.stdout, (
            "Сессия должна остаться active: клиентов в mgmt нет, "
            "значит данным доверять нельзя и cleanup обязан пропустить работу"
        )
        assert "error" not in check.stdout, (
            "Нарушен инвариант C1.7 — cleanup закрыл сессию по пустому ответу mgmt"
        )


class TestContainerLogs:
    """
    Тесты для проверки логов контейнеров.
    """

    @pytest.fixture(scope="class")
    def docker_compose_up(self):
        """
        Поднимает Docker Compose окружение.
        """
        run_docker_compose_cmd(["up", "-d"])
        wait_for_port("localhost", 3306, timeout=60)
        yield
        run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_container_logs_accessible(self, docker_compose_up):
        """
        Логи контейнера доступны для проверки.
        """
        result = subprocess.run(
            ["docker", "logs", "--tail", "10", "openvpn-server"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "Container logs should be accessible"
