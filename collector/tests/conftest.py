"""
Конфигурация pytest для тестов collector модуля.

Содержит фикстуры для работы с БД в тестах.
Переиспользует настройки из core/tests/conftest.py.
"""

import os
import sys

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Импортируем все фикстуры из core/tests/conftest.py
from core.tests.conftest import (
    engine,
    tables,
    db_session as db,
    sample_account,
    sample_session,
    sample_geoip_cache,
)

# Экспортируем фикстуры для использования в тестах
__all__ = [
    'engine',
    'tables',
    'db',
    'sample_account',
    'sample_session',
    'sample_geoip_cache',
]
