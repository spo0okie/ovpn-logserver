"""
Конфигурация Alembic для управления миграциями базы данных.

Этот файл настраивает окружение Alembic для выполнения миграций.
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

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# На этом этапе модели SQLAlchemy не используются (согласно заданию)
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Получаем URL базы данных из переменной окружения или используем дефолтный
DB_URL = os.environ.get(
    "DATABASE_URL",
    "mysql+pymysql://openvpn_user:openvpn_password@localhost/openvpn_logs"
)


def run_migrations_offline() -> None:
    """
    Запуск миграций в 'offline' режиме.

n    В этом режиме URL базы данных передаётся напрямую,
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
    # Переопределяем URL из переменной окружения если она задана
    configuration = config.get_section(config.config_ini_section, {})
    if os.environ.get("DATABASE_URL"):
        configuration["sqlalchemy.url"] = os.environ.get("DATABASE_URL")

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
