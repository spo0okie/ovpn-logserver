"""
Конфигурация Alembic для управления миграциями базы данных.

Этот файл настраивает окружение Alembic для выполнения миграций.
Использует централизованную конфигурацию из core.config.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подключаем metadata моделей для autogenerate и diff-проверок.
from core.database import Base  # noqa: E402
import core.models  # noqa: F401  — регистрируем модели в Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Импортируем централизованную конфигурацию
from core.config import get_database_url

# Получаем URL базы данных из централизованной конфигурации
DB_URL = get_database_url()


def run_migrations_offline() -> None:
    """
    Запуск миграций в 'offline' режиме.

    В этом режиме URL базы данных передаётся напрямую,
    и соединение не создаётся.
    """
    url = config.get_main_option("sqlalchemy.url", DB_URL)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Запуск миграций в 'online' режиме.

    В этом режиме создаётся Engine и устанавливается соединение с БД.
    """
    # Используем URL из централизованной конфигурации
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DB_URL

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
