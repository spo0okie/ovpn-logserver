"""
Конфигурация pytest для тестов базы данных.

Этот файл содержит общие фикстуры и настройки для тестов.
"""

import os
import sys

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
