"""
Аутентификация для Web/API.

Поддерживает:
- Session ID из cookie (для веб-интерфейса).
- Authorization Basic из заголовка (для AJAX/curl).

Пароль хранится в config/auth.yaml как bcrypt-хеш (`password_hash`).
Plaintext-поле `password` поддерживается как legacy с deprecation warning.
"""

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request, status

from core.config import get_web_auth_credentials

logger = logging.getLogger(__name__)


# =============================================================================
# Файловое хранилище сессий
# =============================================================================
SESSION_DIR = os.path.join(os.path.dirname(__file__), "..", "sessions")
SESSION_LIFETIME_SECONDS = 3600

os.makedirs(SESSION_DIR, exist_ok=True)


def create_session(username: str) -> str:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    with open(session_file, "w") as f:
        json.dump({"username": username, "created_at": now, "last_used": now}, f)
    return session_id


def validate_session(session_id: str) -> Optional[str]:
    if not session_id:
        return None

    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(session_file):
        return None

    try:
        with open(session_file, "r") as f:
            data = json.load(f)
        last_used = datetime.fromisoformat(data["last_used"])
    except (json.JSONDecodeError, IOError, KeyError, ValueError) as exc:
        logger.debug("[AUTH] поврежденный файл сессии %s: %s", session_id, exc)
        try:
            os.remove(session_file)
        except OSError:
            pass
        return None

    elapsed = (datetime.now(timezone.utc) - last_used).total_seconds()
    if elapsed > SESSION_LIFETIME_SECONDS:
        try:
            os.remove(session_file)
        except OSError:
            pass
        return None

    data["last_used"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(session_file, "w") as f:
            json.dump(data, f)
    except IOError as exc:
        logger.debug("[AUTH] ошибка обновления сессии %s: %s", session_id, exc)

    return data["username"]


def delete_session(session_id: str) -> bool:
    session_file = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(session_file):
        return False
    try:
        os.remove(session_file)
        return True
    except OSError as exc:
        logger.debug("[AUTH] ошибка удаления сессии %s: %s", session_id, exc)
        return False


def cleanup_expired_sessions() -> int:
    now = datetime.now(timezone.utc)
    expired = 0
    try:
        names = os.listdir(SESSION_DIR)
    except OSError:
        return 0

    for filename in names:
        if not filename.endswith(".json"):
            continue
        path = os.path.join(SESSION_DIR, filename)
        try:
            with open(path, "r") as f:
                data = json.load(f)
            last_used = datetime.fromisoformat(data["last_used"])
            if (now - last_used).total_seconds() > SESSION_LIFETIME_SECONDS:
                os.remove(path)
                expired += 1
        except (json.JSONDecodeError, IOError, KeyError, ValueError):
            try:
                os.remove(path)
                expired += 1
            except OSError:
                pass
    return expired


# =============================================================================
# Проверка пароля
# =============================================================================

_warned_plaintext_password = False


def _verify_password(provided: str, stored_hash: Optional[str], stored_plain: Optional[str]) -> bool:
    """Сравнивает пароль с bcrypt-хешем (приоритет) или plaintext (legacy)."""
    if stored_hash:
        try:
            from passlib.hash import bcrypt
            return bcrypt.verify(provided, stored_hash)
        except (ValueError, TypeError):
            return False

    if stored_plain is not None:
        global _warned_plaintext_password
        if not _warned_plaintext_password:
            logger.warning(
                "[AUTH] Plain-text password в config/auth.yaml небезопасен. "
                "Замените на password_hash (bcrypt)."
            )
            _warned_plaintext_password = True
        return secrets.compare_digest(provided, stored_plain)

    return False


def verify_credentials(username: str, password: str) -> bool:
    """Проверяет username/password по конфигу. Используется login и Basic Auth."""
    cfg = get_web_auth_credentials()
    if not secrets.compare_digest(username, cfg["username"] or ""):
        return False
    return _verify_password(password, cfg.get("password_hash"), cfg.get("password"))


# =============================================================================
# Зависимость FastAPI
# =============================================================================


def get_current_user(request: Request) -> str:
    """
    Аутентифицирует запрос. Приоритет:
    1) session_id cookie (создаётся при логине через /login),
    2) Authorization: Basic ... (для curl/API-клиентов).
    """
    import base64

    session_id = request.cookies.get("session_id")
    if session_id:
        username = validate_session(session_id)
        if username:
            return username

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials format",
                headers={"WWW-Authenticate": "Basic"},
            )
        if verify_credentials(username, password):
            return username
        logger.warning("[AUTH] Basic auth failed for user=%s", username)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Basic"},
    )
