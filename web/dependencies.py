"""
Зависимости FastAPI для веб модуля.

Содержит функции для получения сессии БД и других зависимостей.
Использует централизованную конфигурацию из core.config.
"""

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from core.database import get_db as core_get_db
from core.config import get_database_url_safe


def get_db() -> Generator[Session, None, None]:
    """
    Получает сессию базы данных для использования в endpoints.

    I7.1: API только читает из БД (нет INSERT/UPDATE/DELETE).
    Эта зависимость предоставляет сессию только для чтения.

    Yields:
        Session: Сессия SQLAlchemy
    """
    yield from core_get_db()


def get_db_url_safe() -> str:
    """
    Возвращает безопасный URL БД для логирования (без пароля).
    
    Returns:
        str: DATABASE_URL с замаскированным паролем
    """
    return get_database_url_safe()
