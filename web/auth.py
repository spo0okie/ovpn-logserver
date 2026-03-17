"""
Аутентификация для API - Session-based Auth.

Реализует I7.6: Аутентификация обязательна для всех endpoints.
Учетные данные читаются из config/auth.yaml.
Поддерживает:
- Session ID из cookie для веб-интерфейса
- Authorization заголовок для backward compatibility и AJAX запросов
"""

import logging
import secrets
import uuid
import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict

from fastapi import HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# Импортируем централизованную конфигурацию
from core.config import get_web_auth_credentials

# Настраиваем логирование
logger = logging.getLogger(__name__)


# =============================================================================
# File-based Session Storage
# =============================================================================
# Хранилище сессий в файлах: sessions/{session_id}.json
# Каждый файл содержит: {'username': str, 'created_at': iso_string, 'last_used': iso_string}
SESSION_DIR = os.path.join(os.path.dirname(__file__), "..", "sessions")
SESSION_LIFETIME_SECONDS = 3600

# Убедимся, что директория для сессий существует
os.makedirs(SESSION_DIR, exist_ok=True)


def create_session(username: str) -> str:
    """
    Создает новую сессию для пользователя.
    
    Args:
        username: Имя пользователя
        
    Returns:
        str: Уникальный session_id
    """
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    session_data = {
        'username': username,
        'created_at': now.isoformat(),
        'last_used': now.isoformat()
    }
    
    # Сохраняем сессию в файл
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    with open(session_file, 'w') as f:
        json.dump(session_data, f)
    
    logger.debug(f"[AUTH] Создана новая сессия: session_id={session_id}, username={username}")
    
    return session_id


def validate_session(session_id: str) -> Optional[str]:
    """
    Проверяет валидность сессии и возвращает username.
    
    Args:
        session_id: ID сессии из cookie
        
    Returns:
        str: Имя пользователя если сессия валидна, None если нет
    """
    if not session_id:
        logger.debug(f"[AUTH] validate_session: session_id пуст")
        return None
    
    # Читаем сессию из файла
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(session_file):
        logger.debug(f"[AUTH] validate_session: session_id={session_id} не найден в файловом хранилище")
        return None
    
    try:
        with open(session_file, 'r') as f:
            session_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.debug(f"[AUTH] validate_session: ошибка чтения сессии {session_id}: {e}")
        # Удаляем поврежденный файл
        try:
            os.remove(session_file)
        except OSError:
            pass
        return None
    
    # Проверяем время жизни сессии
    now = datetime.now(timezone.utc)
    try:
        last_used = datetime.fromisoformat(session_data['last_used'])
    except (ValueError, KeyError):
        logger.debug(f"[AUTH] validate_session: неверный формат времени в сессии {session_id}")
        # Удаляем поврежденный файл
        try:
            os.remove(session_file)
        except OSError:
            pass
        return None
    
    # Проверяем не истекла ли сессия
    elapsed = (now - last_used).total_seconds()
    if elapsed > SESSION_LIFETIME_SECONDS:
        # Удаляем просроченную сессию
        logger.debug(f"[AUTH] validate_session: session_id={session_id} истекла (прошло {elapsed}с)")
        try:
            os.remove(session_file)
        except OSError:
            pass
        return None
    
    # Обновляем время последнего использования
    session_data['last_used'] = now.isoformat()
    try:
        with open(session_file, 'w') as f:
            json.dump(session_data, f)
    except IOError as e:
        logger.debug(f"[AUTH] validate_session: ошибка обновления сессии {session_id}: {e}")
    
    logger.debug(f"[AUTH] validate_session: session_id={session_id} валидна, username={session_data['username']}")
    return session_data['username']


def delete_session(session_id: str) -> bool:
    """
    Удаляет сессию (логаут).
    
    Args:
        session_id: ID сессии для удаления
        
    Returns:
        bool: True если сессия была удалена, False если не существовала
    """
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
            return True
        except OSError as e:
            logger.debug(f"[AUTH] delete_session: ошибка удаления файла сессии {session_id}: {e}")
            return False
    return False


def cleanup_expired_sessions() -> int:
    """
    Очищает все просроченные сессии.
    
    Returns:
        int: Количество удаленных сессий
    """
    now = datetime.now(timezone.utc)
    expired_count = 0
    
    # Проверяем все файлы сессий в директории
    try:
        for filename in os.listdir(SESSION_DIR):
            if filename.endswith(".json"):
                session_id = filename[:-5]  # Убираем .json
                session_file = os.path.join(SESSION_DIR, filename)
                
                try:
                    with open(session_file, 'r') as f:
                        session_data = json.load(f)
                    
                    last_used = datetime.fromisoformat(session_data['last_used'])
                    elapsed = (now - last_used).total_seconds()
                    
                    if elapsed > SESSION_LIFETIME_SECONDS:
                        # Удаляем просроченную сессию
                        os.remove(session_file)
                        expired_count += 1
                        
                except (json.JSONDecodeError, IOError, KeyError, ValueError) as e:
                    logger.debug(f"[AUTH] cleanup_expired_sessions: ошибка обработки {session_file}: {e}")
                    # Удаляем поврежденный файл
                    try:
                        os.remove(session_file)
                        expired_count += 1
                    except OSError:
                        pass
                        
    except OSError as e:
        logger.debug(f"[AUTH] cleanup_expired_sessions: ошибка доступа к директории {SESSION_DIR}: {e}")
    
    return expired_count


# HTTPBasic для FastAPI (backward compatibility)
db_security = HTTPBasic(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = None
) -> str:
    """
    Проверяет аутентификацию пользователя.
    
    I7.6: Аутентификация обязательна для всех endpoints.
    Учетные данные читаются из config/auth.yaml.
    
    Поддерживает:
    1. Session ID из cookie (session_id) - для веб-интерфейса
    2. Authorization заголовок - для backward compatibility и AJAX запросов
    
    Args:
        request: HTTP запрос
        credentials: Basic Auth credentials (опционально)
    
    Returns:
        str: Имя пользователя при успешной аутентификации
    
    Raises:
        HTTPException: 401 если аутентификация не пройдена
    """
    import base64
    
    logger.debug(f"[AUTH] get_current_user: проверка аутентификации")
    logger.debug(f"[AUTH] Cookies: {list(request.cookies.keys())}")
    logger.debug(f"[AUTH] Cookie values: {dict(request.cookies)}")
    logger.debug(f"[AUTH] Headers: {dict(request.headers)}")
    
    # Приоритет 1: Session ID из cookie
    session_id = request.cookies.get("session_id")
    logger.debug(f"[AUTH] session_id из cookie: {session_id}")
    logger.debug(f"[AUTH] Тип session_id: {type(session_id)}, длина: {len(session_id) if session_id else 0}")
    if session_id:
        username = validate_session(session_id)
        if username:
            logger.debug(f"[AUTH] Аутентификация успешна через session_id, username={username}")
            return username
        logger.debug(f"[AUTH] session_id не валиден")
    
    # Приоритет 2: Authorization заголовок (backward compatibility)
    auth_header = request.headers.get("Authorization", "")
    
    if auth_header.startswith("Basic "):
        try:
            encoded = auth_header[6:]  # Пропускаем "Basic "
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials format",
                headers={"WWW-Authenticate": "Basic"},
            )
    
    # Приоритет 3: Old auth cookie (backward compatibility)
    else:
        auth_cookie = request.cookies.get("auth", "")
        if not auth_cookie:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic"},
            )
        
        try:
            # Cookie содержит base64-encoded credentials
            decoded = base64.b64decode(auth_cookie).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid cookie format",
                headers={"WWW-Authenticate": "Basic"},
            )

    # Получаем учетные данные из конфигурации
    auth_config = get_web_auth_credentials()
    valid_username = auth_config.get("username", "admin")
    valid_password = auth_config.get("password", "admin_password_123")

    logger.debug(f"[AUTH] Проверка учетных данных: username={username}, valid_username={valid_username}")

    # Проверяем username (константное время для предотвращения timing attacks)
    if not secrets.compare_digest(username, valid_username):
        logger.warning(f"[AUTH] Неверное имя пользователя: {username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Проверяем password (константное время для предотвращения timing attacks)
    if not secrets.compare_digest(password, valid_password):
        logger.warning(f"[AUTH] Неверный пароль для пользователя: {username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    logger.info(f"[AUTH] Успешная аутентификация: username={username}")
    return username
