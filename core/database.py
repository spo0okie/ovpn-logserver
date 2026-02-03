"""
Настройка подключения к базе данных.

Содержит engine, SessionLocal и declarative_base для SQLAlchemy моделей.
Использует централизованную конфигурацию из core.config.
Поддерживает переопределение DATABASE_URL через переменную окружения для тестов.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# Импортируем централизованную конфигурацию
from core.config import get_database_url, get_engine_kwargs


def get_engine_instance():
    """
    Создает и возвращает SQLAlchemy engine.
    
    Функция позволяет пересоздавать engine при изменении конфигурации.
    Поддерживает переопределение DATABASE_URL через переменную окружения для тестов.
    
    Returns:
        Engine: SQLAlchemy engine
    """
    # Проверяем переменную окружения DATABASE_URL (для тестов)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        database_url = get_database_url()
    
    engine_kwargs = get_engine_kwargs()
    
    # Для SQLite используем специальные параметры
    if "sqlite" in database_url:
        engine_kwargs = {
            "connect_args": {"check_same_thread": False}
        }
    
    return create_engine(database_url, **engine_kwargs)


def get_session_local():
    """
    Создает и возвращает фабрику сессий.
    
    Returns:
        sessionmaker: Фабрика сессий SQLAlchemy
    """
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )


# Получаем URL базы данных из централизованной конфигурации
# или из переменной окружения DATABASE_URL (для тестов)
# Формат: mysql+pymysql://user:password@host:port/database
DATABASE_URL = os.getenv("DATABASE_URL") or get_database_url()

# Создаем engine для подключения к БД
# pool_pre_ping=True проверяет соединение перед использованием
# echo=False отключает вывод SQL запросов (включить для отладки)
engine = get_engine_instance()

# Создаем фабрику сессий
# autocommit=False - транзакции управляются явно
# autoflush=False - отложенная запись в БД до commit
SessionLocal = get_session_local()

# Базовый класс для декларативных моделей (I2.1)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Генератор сессий базы данных для использования в зависимостях (FastAPI и т.д.).
    
    Использование:
        @app.get("/items/")
        def read_items(db: Session = Depends(get_db)):
            ...
    
    Yields:
        Session: Сессия SQLAlchemy
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Инициализация базы данных - создание всех таблиц.
    
    ВНИМАНИЕ: В production используйте Alembic миграции!
    Эта функция полезна для тестов и разработки.
    """
    # Импортируем модели, чтобы они были зарегистрированы в Base.metadata
    from . import models  # noqa: F401
    
    Base.metadata.create_all(bind=engine)
