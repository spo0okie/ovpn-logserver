#!/usr/bin/env python3
"""
Конфигурация pytest для E2E тестов в Docker.

Предоставляет фикстуры для управления Docker Compose окружением.
"""

import os
import subprocess
import pytest
import sys

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_docker_compose_cmd(cmd: list, cwd: str = None) -> subprocess.CompletedProcess:
    """
    Запускает команду docker-compose из корневой директории проекта.
    
    Args:
        cmd: Команда для выполнения
        cwd: Рабочая директория
    
    Returns:
        Результат выполнения команды
    """
    # Определяем корневую директорию проекта
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    docker_compose_file = os.path.join(project_root, "docker", "docker-compose.yml")
    
    full_cmd = ["docker", "compose", "-f", docker_compose_file] + cmd
    return subprocess.run(
        full_cmd, 
        cwd=cwd or project_root, 
        capture_output=True, 
        text=True
    )


@pytest.fixture(scope="session")
def docker_compose_project():
    """
    Фикстура сессии: поднимает Docker Compose окружение один раз.
    
    Yields:
        Результат запуска docker-compose up -d
    """
    # Останавливаем любые существующие контейнеры
    run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Поднимаем окружение
    result = run_docker_compose_cmd(["up", "-d"])
    
    if result.returncode != 0:
        pytest.skip(f"Docker Compose failed to start: {result.stderr}")
    
    yield result
    
    # После всех тестов останавливаем окружение
    run_docker_compose_cmd(["down"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="function")
def clean_docker_state(docker_compose_project):
    """
    Фикстура функции: очищает тестовые данные перед каждым тестом.
    
    Yields:
        None
    """
    # Очищаем тестовые данные в БД
    try:
        cleanup_result = subprocess.run(
            ["docker", "exec",
             "-e", f"MYSQL_PWD={os.environ.get('MYSQL_PASSWORD', 'openvpn_password')}",
             "openvpn-mysql", "mysql",
             f"-u{os.environ.get('MYSQL_USER', 'openvpn')}",
             os.environ.get("MYSQL_DATABASE", "openvpn_logs"), "-e", """
                DELETE s FROM sessions s JOIN accounts a ON a.id = s.account_id
                WHERE a.cn LIKE '%_e2e' OR a.cn LIKE 'test_%'
             """],
            capture_output=True,
            text=True,
            timeout=10
        )
        # Также очищаем тестовые аккаунты
        subprocess.run(
            ["docker", "exec",
             "-e", f"MYSQL_PWD={os.environ.get('MYSQL_PASSWORD', 'openvpn_password')}",
             "openvpn-mysql", "mysql",
             f"-u{os.environ.get('MYSQL_USER', 'openvpn')}",
             os.environ.get("MYSQL_DATABASE", "openvpn_logs"), "-e", """
                DELETE FROM accounts WHERE cn LIKE '%_e2e' OR cn LIKE 'test_%'
             """],
            capture_output=True,
            text=True,
            timeout=10
        )
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    yield
    
    # Очищаем после теста
    try:
        subprocess.run(
            ["docker", "exec",
             "-e", f"MYSQL_PWD={os.environ.get('MYSQL_PASSWORD', 'openvpn_password')}",
             "openvpn-mysql", "mysql",
             f"-u{os.environ.get('MYSQL_USER', 'openvpn')}",
             os.environ.get("MYSQL_DATABASE", "openvpn_logs"), "-e", """
                DELETE s FROM sessions s JOIN accounts a ON a.id = s.account_id
                WHERE a.cn LIKE '%_e2e' OR a.cn LIKE 'test_%'
             """],
            capture_output=True,
            text=True,
            timeout=10
        )
        subprocess.run(
            ["docker", "exec",
             "-e", f"MYSQL_PWD={os.environ.get('MYSQL_PASSWORD', 'openvpn_password')}",
             "openvpn-mysql", "mysql",
             f"-u{os.environ.get('MYSQL_USER', 'openvpn')}",
             os.environ.get("MYSQL_DATABASE", "openvpn_logs"), "-e", """
                DELETE FROM accounts WHERE cn LIKE '%_e2e' OR cn LIKE 'test_%'
             """],
            capture_output=True,
            text=True,
            timeout=10
        )
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass


def pytest_configure(config):
    """
    Регистрирует маркер для пропуска тестов без Docker.
    """
    config.addinivalue_line(
        "markers", "docker: marker for tests requiring Docker"
    )


def pytest_collection_modifyitems(config, items):
    """
    Пропускает тесты если Docker недоступен.
    """
    docker_available = False
    try:
        result = subprocess.run(
            ["docker", "ps"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        docker_available = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        docker_available = False
    
    if not docker_available:
        pytest.skip("Docker is not available")
