"""
Аутентификация для API - Basic Auth.

Реализует I7.6: Аутентификация обязательна для всех endpoints.
"""

import os
import secrets
from typing import Optional

from fastapi import HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials


# HTTPBasic для FastAPI
db_security = HTTPBasic(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = None
) -> str:
    """
    Проверяет Basic Auth credentials.

    I7.6: Аутентификация обязательна для всех endpoints.

    Args:
        request: HTTP запрос
        credentials: Basic Auth credentials

    Returns:
        str: Имя пользователя при успешной аутентификации

    Raises:
        HTTPException: 401 если аутентификация не пройдена
    """
    # Получаем credentials из заголовка Authorization
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    import base64
    try:
        # Декодируем base64
        encoded = auth_header[6:]  # Пропускаем "Basic "
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials format",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Получаем пользователей из переменной окружения
    # Формат: user1:pass1,user2:pass2
    api_users = os.getenv("API_USERS", "admin:admin")

    valid_users = {}
    for user_pass in api_users.split(","):
        if ":" in user_pass:
            user, pwd = user_pass.split(":", 1)
            valid_users[user] = pwd

    # Проверяем credentials
    if username not in valid_users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Константное время сравнения для предотвращения timing attacks
    if not secrets.compare_digest(password, valid_users[username]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return username
