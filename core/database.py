"""
Настройка подключения к базе данных.

Содержит engine, SessionLocal и declarative_base для SQLAlchemy моделей.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# Получаем URL базы данных из переменной окружения или используем значение по умолчанию
# Формат: mysql+pymysql://user:password@host:port/database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://openvpn:openvpn_password@localhost:3306/openvpn_logs"
)

# Создаем engine для подключения к БД
# pool_pre_ping=True проверяет соединение перед использованием
# echo=False отключает вывод SQL запросов (включить для отладки)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    # Для MySQL важно указать кодировку
    connect_args={
        "charset": "utf8mb4"
    } if "mysql" in DATABASE_URL else {}
)

# Создаем фабрику сессий
# autocommit=False - транзакции управляются явно
# autoflush=False - отложенная запись в БД до commit
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

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