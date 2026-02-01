"""
Интеграционные и E2E тесты для Docker окружения.

Тесты проверяют инварианты этапа 9:
- I9.1: docker-compose up поднимает все сервисы
- I9.2: OpenVPN сервер генерирует PKI при первом запуске
- I9.3: Клиент может подключиться к серверу
- I9.4: При подключении создается запись в БД
- I9.5: При отключении сессия закрывается

Запуск тестов:
    cd docker && python -m pytest tests/test_docker.py -v

Требования:
    pip install docker pytest requests pymysql sqlalchemy
"""

import subprocess
import time
import os
import sys
import pytest
import socket
from datetime import datetime, timedelta
from typing import Optional, Generator

# Добавляем родительскую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Пытаемся импортировать docker библиотеку
try:
    import docker as docker_lib
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

# Пытаемся импортировать requests
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Пытаемся импортировать SQLAlchemy
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


# =============================================================================
# Фикстуры
# =============================================================================

@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    """Путь к docker-compose файлу."""
    return os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")


@pytest.fixture(scope="session")
def project_root() -> str:
    """Корневая директория проекта."""
    return os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="session")
def docker_client():
    """Docker клиент."""
    if not DOCKER_AVAILABLE:
        pytest.skip("docker library not installed")
    return docker_lib.from_env()


@pytest.fixture(scope="session")
def db_engine():
    """SQLAlchemy engine для подключения к БД."""
    if not SQLALCHEMY_AVAILABLE:
        pytest.skip("sqlalchemy not installed")
    
    # Подключаемся к MySQL через exposed порт
    database_url = "mysql+pymysql://openvpn:openvpn_password@localhost:3306/openvpn_logs"
    engine = create_engine(database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Сессия базы данных для тестов."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


# =============================================================================
# Вспомогательные функции
# =============================================================================

def run_command(cmd: list, cwd: Optional[str] = None, timeout: int = 60) -> tuple:
    """
    Выполняет shell команду и возвращает результат.
    
    Args:
        cmd: Список аргументов команды
        cwd: Рабочая директория
        timeout: Таймаут в секундах
    
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


def wait_for_port(host: str, port: int, timeout: int = 60) -> bool:
    """
    Ожидает пока порт станет доступен.
    
    Args:
        host: Хост
        port: Порт
        timeout: Таймаут в секундах
    
    Returns:
        True если порт доступен, False если таймаут
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError):
            time.sleep(1)
    return False


def wait_for_mysql(timeout: int = 120) -> bool:
    """Ожидает пока MySQL станет доступен."""
    return wait_for_port("localhost", 3306, timeout)


def wait_for_web(timeout: int = 60) -> bool:
    """Ожидает пока Web приложение станет доступно."""
    if not REQUESTS_AVAILABLE:
        return wait_for_port("localhost", 8000, timeout)
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get("http://localhost:8000/health", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def wait_for_openvpn(timeout: int = 60) -> bool:
    """Ожидает пока OpenVPN сервер станет доступен."""
    return wait_for_port("localhost", 1194, timeout)


# =============================================================================
# Тесты I9.1: docker-compose up поднимает все сервисы
# =============================================================================

class TestI91_ComposeUp:
    """Тесты для инварианта I9.1: docker-compose up поднимает все сервисы."""
    
    def test_compose_file_exists(self, docker_compose_file: str):
        """Проверяет что docker-compose.yml существует."""
        assert os.path.exists(docker_compose_file), f"docker-compose.yml not found at {docker_compose_file}"
    
    def test_compose_config_valid(self, project_root: str):
        """Проверяет что конфигурация docker-compose валидна."""
        code, stdout, stderr = run_command(
            ["docker-compose", "config"],
            cwd=project_root
        )
        assert code == 0, f"Invalid docker-compose config: {stderr}"
    
    @pytest.mark.integration
    def test_mysql_service_starts(self, project_root: str):
        """Проверяет что MySQL сервис запускается."""
        # Запускаем только MySQL
        code, stdout, stderr = run_command(
            ["docker-compose", "up", "-d", "mysql"],
            cwd=project_root,
            timeout=120
        )
        assert code == 0, f"Failed to start MySQL: {stderr}"
        
        # Ждем пока MySQL станет доступен
        assert wait_for_mysql(120), "MySQL did not become ready in time"
    
    @pytest.mark.integration
    def test_web_service_starts(self, project_root: str):
        """Проверяет что Web сервис запускается."""
        # Запускаем web (зависит от mysql)
        code, stdout, stderr = run_command(
            ["docker-compose", "up", "-d", "web"],
            cwd=project_root,
            timeout=120
        )
        assert code == 0, f"Failed to start Web: {stderr}"
        
        # Ждем пока Web станет доступен
        assert wait_for_web(60), "Web did not become ready in time"
    
    @pytest.mark.integration
    def test_openvpn_server_starts(self, project_root: str):
        """Проверяет что OpenVPN сервер запускается."""
        code, stdout, stderr = run_command(
            ["docker-compose", "up", "-d", "openvpn-server"],
            cwd=project_root,
            timeout=120
        )
        assert code == 0, f"Failed to start OpenVPN server: {stderr}"
        
        # Даем время на генерацию PKI
        time.sleep(30)
        
        # Проверяем что контейнер запущен
        code, stdout, stderr = run_command(
            ["docker-compose", "ps", "-q", "openvpn-server"],
            cwd=project_root
        )
        assert code == 0 and stdout.strip(), "OpenVPN server container is not running"


# =============================================================================
# Тесты I9.2: OpenVPN сервер генерирует PKI при первом запуске
# =============================================================================

class TestI92_PkiGeneration:
    """Тесты для инварианта I9.2: OpenVPN сервер генерирует PKI при первом запуске."""
    
    @pytest.mark.integration
    def test_ca_certificate_exists(self, project_root: str):
        """Проверяет что CA сертификат создан."""
        # Проверяем в контейнере
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/pki/ca.crt"],
            cwd=project_root
        )
        assert code == 0, "CA certificate not found"
    
    @pytest.mark.integration
    def test_server_certificate_exists(self, project_root: str):
        """Проверяет что сертификат сервера создан."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/pki/issued/server.crt"],
            cwd=project_root
        )
        assert code == 0, "Server certificate not found"
    
    @pytest.mark.integration
    def test_server_key_exists(self, project_root: str):
        """Проверяет что ключ сервера создан."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/pki/private/server.key"],
            cwd=project_root
        )
        assert code == 0, "Server key not found"
    
    @pytest.mark.integration
    def test_dh_params_exist(self, project_root: str):
        """Проверяет что DH параметры созданы."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/pki/dh.pem"],
            cwd=project_root
        )
        assert code == 0, "DH parameters not found"
    
    @pytest.mark.integration
    def test_crl_exists(self, project_root: str):
        """Проверяет что CRL файл создан."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/pki/crl.pem"],
            cwd=project_root
        )
        assert code == 0, "CRL file not found"
    
    @pytest.mark.integration
    def test_ta_key_exists(self, project_root: str):
        """Проверяет что TLS-auth ключ создан."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/ta.key"],
            cwd=project_root
        )
        assert code == 0, "TA key not found"
    
    @pytest.mark.integration
    def test_client_certificate_exists(self, project_root: str):
        """Проверяет что клиентский сертификат создан."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "test", "-f", "/etc/openvpn/certs/test-client.crt"],
            cwd=project_root
        )
        assert code == 0, "Client certificate not found"
    
    @pytest.mark.integration
    def test_certificates_shared_via_volume(self, project_root: str):
        """Проверяет что сертификаты доступны через volume."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "ls", "-la", "/etc/openvpn/certs/"],
            cwd=project_root
        )
        assert code == 0, "Certs directory not accessible"
        assert "ca.crt" in stdout, "ca.crt not in certs directory"
        assert "test-client.crt" in stdout, "test-client.crt not in certs directory"


# =============================================================================
# Тесты I9.3: Клиент может подключиться к серверу
# =============================================================================

class TestI93_ClientConnection:
    """Тесты для инварианта I9.3: Клиент может подключиться к серверу."""
    
    @pytest.mark.integration
    def test_openvpn_port_listening(self, project_root: str):
        """Проверяет что OpenVPN сервер слушает порт 1194."""
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-server", "netstat", "-uln"],
            cwd=project_root
        )
        # Проверяем что порт 1194 открыт
        assert ":1194" in stdout or "0.0.0.0:1194" in stdout, "OpenVPN is not listening on port 1194"
    
    @pytest.mark.integration
    def test_client_container_starts(self, project_root: str):
        """Проверяет что клиентский контейнер запускается."""
        # Запускаем клиента
        code, stdout, stderr = run_command(
            ["docker-compose", "--profile", "client", "up", "-d", "openvpn-client"],
            cwd=project_root,
            timeout=120
        )
        assert code == 0, f"Failed to start OpenVPN client: {stderr}"
        
        # Ждем инициализации
        time.sleep(10)
        
        # Проверяем что контейнер запущен
        code, stdout, stderr = run_command(
            ["docker-compose", "ps", "-q", "openvpn-client"],
            cwd=project_root
        )
        assert code == 0 and stdout.strip(), "OpenVPN client container is not running"
    
    @pytest.mark.integration
    def test_client_receives_certificates(self, project_root: str):
        """Проверяет что клиент получает сертификаты от сервера."""
        # Проверяем что сертификаты скопированы
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-client", "test", "-f", "/etc/openvpn/client/ca.crt"],
            cwd=project_root
        )
        assert code == 0, "Client did not receive CA certificate"
    
    @pytest.mark.e2e
    def test_client_connects_to_server(self, project_root: str):
        """
        E2E тест: Проверяет что клиент подключается к серверу.
        
        Этот тест требует запущенных сервисов и может занять некоторое время.
        """
        # Запускаем клиента с командой connect
        code, stdout, stderr = run_command(
            ["docker-compose", "--profile", "client", "exec", "-d", "openvpn-client", "/entrypoint.sh", "connect"],
            cwd=project_root,
            timeout=60
        )
        
        # Ждем установления соединения
        time.sleep(15)
        
        # Проверяем что tun интерфейс создан
        code, stdout, stderr = run_command(
            ["docker-compose", "exec", "-T", "openvpn-client", "ip", "link", "show", "tun0"],
            cwd=project_root
        )
        assert code == 0, "TUN interface not created, connection failed"


# =============================================================================
# Тесты I9.4: При подключении создается запись в БД
# =============================================================================

class TestI94_SessionCreation:
    """Тесты для инварианта I9.4: При подключении создается запись в БД."""
    
    @pytest.mark.e2e
    def test_session_created_on_connect(self, project_root: str, db_session):
        """
        E2E тест: Проверяет что при подключении клиента создается сессия в БД.
        """
        # Запоминаем текущее количество сессий
        from sqlalchemy import text
        result = db_session.execute(text("SELECT COUNT(*) FROM sessions"))
        initial_count = result.scalar()
        
        # Запускаем клиента
        code, stdout, stderr = run_command(
            ["docker-compose", "--profile", "client", "exec", "-d", "openvpn-client", "/entrypoint.sh", "connect"],
            cwd=project_root,
            timeout=60
        )
        
        # Ждем пока сессия создастся
        time.sleep(10)
        
        # Проверяем что сессия создана
        result = db_session.execute(text("""
            SELECT COUNT(*) FROM sessions 
            WHERE status = 'active' AND account_id IN (
                SELECT id FROM accounts WHERE cn = 'test-client'
            )
        """))
        new_count = result.scalar()
        
        assert new_count > 0, "No active session created for test-client"
    
    @pytest.mark.e2e
    def test_account_created_for_client(self, project_root: str, db_session):
        """
        E2E тест: Проверяет что аккаунт создается для подключающегося клиента.
        """
        from sqlalchemy import text
        
        # Проверяем что аккаунт test-client существует
        result = db_session.execute(
            text("SELECT cn, created_at FROM accounts WHERE cn = 'test-client'")
        )
        account = result.fetchone()
        
        assert account is not None, "Account for test-client not found"
        assert account[0] == "test-client", "Account CN mismatch"
    
    @pytest.mark.e2e
    def test_session_has_correct_data(self, project_root: str, db_session):
        """
        E2E тест: Проверяет что сессия содержит корректные данные.
        """
        from sqlalchemy import text
        
        # Ждем немного для обработки подключения
        time.sleep(5)
        
        # Проверяем данные сессии
        result = db_session.execute(text("""
            SELECT s.source_ip, s.virtual_ip, s.status, a.cn
            FROM sessions s
            JOIN accounts a ON s.account_id = a.id
            WHERE a.cn = 'test-client'
            ORDER BY s.connected_at DESC
            LIMIT 1
        """))
        session = result.fetchone()
        
        if session:
            assert session[0] is not None, "Session source_ip is null"
            assert session[2] == "active", "Session status should be 'active'"
            assert session[3] == "test-client", "Session belongs to wrong account"


# =============================================================================
# Тесты I9.5: При отключении сессия закрывается
# =============================================================================

class TestI95_SessionClose:
    """Тесты для инварианта I9.5: При отключении сессия закрывается."""
    
    @pytest.mark.e2e
    def test_session_closed_on_disconnect(self, project_root: str, db_session):
        """
        E2E тест: Проверяет что при отключении клиента сессия закрывается.
        """
        from sqlalchemy import text
        
        # Запоминаем текущую активную сессию
        result = db_session.execute(text("""
            SELECT id FROM sessions 
            WHERE status = 'active' AND account_id IN (
                SELECT id FROM accounts WHERE cn = 'test-client'
            )
            ORDER BY connected_at DESC
            LIMIT 1
        """))
        session_row = result.fetchone()
        
        if not session_row:
            pytest.skip("No active session found for test-client")
        
        session_id = session_row[0]
        
        # Останавливаем клиента
        code, stdout, stderr = run_command(
            ["docker-compose", "--profile", "client", "stop", "openvpn-client"],
            cwd=project_root,
            timeout=60
        )
        
        # Ждем пока сработает скрипт отключения
        time.sleep(10)
        
        # Проверяем что сессия закрыта
        result = db_session.execute(
            text("SELECT status, disconnected_at FROM sessions WHERE id = :id"),
            {"id": session_id}
        )
        session = result.fetchone()
        
        assert session is not None, "Session not found"
        assert session[0] == "closed", f"Session status should be 'closed', got '{session[0]}'"
        assert session[1] is not None, "disconnected_at should be set"
    
    @pytest.mark.e2e
    def test_session_traffic_stats_saved(self, project_root: str, db_session):
        """
        E2E тест: Проверяет что статистика трафика сохраняется при отключении.
        """
        from sqlalchemy import text
        
        # Проверяем закрытые сессии
        result = db_session.execute(text("""
            SELECT bytes_sent, bytes_received 
            FROM sessions 
            WHERE status = 'closed' AND account_id IN (
                SELECT id FROM accounts WHERE cn = 'test-client'
            )
            ORDER BY disconnected_at DESC
            LIMIT 1
        """))
        session = result.fetchone()
        
        if session:
            # bytes_sent и bytes_received могут быть 0 в тестовом окружении
            # но они должны быть установлены (не NULL)
            assert session[0] is not None, "bytes_sent should not be null"
            assert session[1] is not None, "bytes_received should not be null"


# =============================================================================
# Cleanup фикстура
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def cleanup_containers(project_root: str):
    """
    Очищает контейнеры после всех тестов.
    """
    yield
    
    # Останавливаем и удаляем контейнеры
    run_command(
        ["docker-compose", "--profile", "client", "down", "-v"],
        cwd=project_root,
        timeout=120
    )


# =============================================================================
# Запуск тестов из командной строки
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
