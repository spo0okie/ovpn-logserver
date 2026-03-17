"""
HTML endpoints для Web UI.

I8.1: UI использует только REST API (прямых запросов к БД нет)
I8.2: Все страницы требуют аутентификации
"""

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import get_web_auth_credentials
from web.utils.timezone import format_datetime, get_local_tz
from web.auth import create_session, delete_session, validate_session

# Настраиваем логирование
logger = logging.getLogger(__name__)


router = APIRouter(tags=["pages"])

# Настройка шаблонов Jinja2
templates = Jinja2Templates(directory="web/templates")

# Регистрируем фильтр для конвертации UTC времени в локальное
# Используется в шаблонах: {{ datetime | local_datetime }}
templates.env.filters['local_datetime'] = format_datetime


def get_api_base_url(request: Request) -> str:
    """Возвращает базовый URL для API запросов."""
    # Для локальных запросов используем относительный URL
    return ""


def get_auth_headers(request: Request) -> dict:
    """
    Получает заголовки авторизации из сессии.
    
    I8.2: Проверка аутентификации для всех страниц.
    """
    session_user = request.session.get("user") if hasattr(request, "session") else None
    session_pass = request.session.get("password") if hasattr(request, "session") else None
    
    # Если нет сессии, проверяем Basic Auth заголовок
    if not session_user:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                encoded = auth_header[6:]
                decoded = base64.b64decode(encoded).decode("utf-8")
                session_user, session_pass = decoded.split(":", 1)
            except Exception:
                pass
    
    if not session_user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    credentials = base64.b64encode(f"{session_user}:{session_pass}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


def verify_credentials(username: str, password: str) -> bool:
    """
    Проверяет учетные данные пользователя.

    Использует централизованную конфигурацию из config/auth.yaml.
    I7.6: Аутентификация обязательна для всех endpoints.

    Args:
        username: Имя пользователя
        password: Пароль

    Returns:
        bool: True если учетные данные верны
    """
    import secrets

    # Получаем учетные данные из централизованной конфигурации
    auth_config = get_web_auth_credentials()
    valid_username = auth_config.get("username", "admin")
    valid_password = auth_config.get("password", "admin_password_123")

    # Проверяем username
    if not secrets.compare_digest(username, valid_username):
        return False

    # Проверяем password (константное время для предотвращения timing attacks)
    return secrets.compare_digest(password, valid_password)


# =============================================================================
# Auth Pages
# =============================================================================

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None):
    """Страница входа."""
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember: bool = Form(False)
):
    """
    Обработка формы входа.
    
    При успешном входе создает сессию и устанавливает session_id cookie.
    """
    logger.info(f"[LOGIN] Попытка входа: username={username}")
    
    if not verify_credentials(username, password):
        logger.warning(f"[LOGIN] Неверные учетные данные: username={username}")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401
        )
    
    # Создаем сессию
    session_id = create_session(username)
    logger.info(f"[LOGIN] Сессия создана: session_id={session_id}, username={username}")
    
    # Устанавливаем session_id cookie
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=86400 if remember else 3600,  # 1 день или 1 час
        httponly=True,  # Защита от XSS
        samesite="lax",
        secure=False  # В продакшене установить True
    )
    logger.debug(f"[LOGIN] Cookie установлена: session_id={session_id}")
    logger.debug(f"[LOGIN] Response headers: {dict(response.headers)}")
    
    # Также пробуем установить сессию если доступна (FastAPI session middleware)
    try:
        if "session" in request.scope:
            request.session["user"] = username
    except Exception:
        pass
    
    logger.info(f"[LOGIN] Успешный вход: username={username}, перенаправление на /")
    return response


@router.get("/logout")
def logout(request: Request):
    """Выход из системы - удаляет сессию."""
    # Получаем session_id из cookie для удаления
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_session(session_id)
    
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_id")
    
    # Также удаляем old auth cookie для backward compatibility
    response.delete_cookie("auth")
    
    # Проверяем наличие session без вызова свойства
    try:
        if "session" in request.scope:
            request.session.clear()
    except Exception:
        pass
    
    return response


# =============================================================================
# Dashboard
# =============================================================================

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """
    Dashboard с обзором метрик.
    
    I8.1: Получаем данные через API
    I8.2: Требуется аутентификация
    """
    logger.debug(f"[DASHBOARD] Запрос к dashboard, cookies: {list(request.cookies.keys())}")
    # Получаем авторизационные заголовки
    auth_headers = _get_auth_from_cookie(request)
    logger.debug(f"[DASHBOARD] Авторизация успешна")
    
    try:
        # I8.1: Запрос к API для получения статистики
        response = requests.get(
            "http://127.0.0.1:8000/api/v1/stats/overview",
            headers=auth_headers,
            timeout=5
        )
        response.raise_for_status()
        stats = response.json()
    except Exception as e:
        # Если API недоступен, показываем пустые данные
        stats = {
            "accounts": {"total": 0, "active_certs": 0, "revoked": 0, "with_ccd": 0, "expiring_soon": 0},
            "sessions": {"active": 0, "today": 0, "this_week": 0, "this_month": 0},
            "attempts": {"failed_today": 0, "failed_this_week": 0}
        }
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": stats,
            "now": format_datetime(datetime.now(timezone.utc))
        }
    )


# =============================================================================
# Accounts
# =============================================================================

@router.get("/accounts", response_class=HTMLResponse)
def accounts_list(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    is_revoked: Optional[str] = None,
    has_ccd: Optional[str] = None,
    sort_by: str = "cn",
    sort_order: str = "asc"
):
    """
    Список аккаунтов.
    
    I8.1: Получаем данные через API
    """
    auth_headers = _get_auth_from_cookie(request)
    
    # Формируем параметры запроса
    params = {"page": page, "per_page": per_page, "sort_by": sort_by, "sort_order": sort_order}
    if search:
        params["search"] = search
    if is_revoked is not None and is_revoked != "":
        params["is_revoked"] = is_revoked.lower() == "true"
    if has_ccd is not None and has_ccd != "":
        params["has_ccd"] = has_ccd.lower() == "true"
    
    try:
        response = requests.get(
            "http://127.0.0.1:8000/api/v1/accounts",
            headers=auth_headers,
            params=params,
            timeout=5
        )
        response.raise_for_status()
        accounts = response.json()
    except Exception:
        accounts = {"data": [], "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0, "sort_by": sort_by, "sort_order": sort_order}}
    
    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "accounts": accounts,
            "search": search,
            "is_revoked": is_revoked,
            "has_ccd": has_ccd,
            "now": format_datetime(datetime.now(timezone.utc))
        }
    )


@router.get("/accounts/{cn}", response_class=HTMLResponse)
def account_detail(
    request: Request,
    cn: str,
    page: int = 1,
    per_page: int = 10
):
    """
    Детали аккаунта и история сессий.
    
    I8.1: Получаем данные через API
    """
    auth_headers = _get_auth_from_cookie(request)
    
    try:
        # Получаем детали аккаунта
        response = requests.get(
            f"http://127.0.0.1:8000/api/v1/accounts/{cn}",
            headers=auth_headers,
            timeout=5
        )
        response.raise_for_status()
        account = response.json()
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Account not found")
        account = {}
    except Exception:
        account = {}
    
    # Получаем историю сессий аккаунта
    try:
        response = requests.get(
            f"http://127.0.0.1:8000/api/v1/accounts/{cn}/sessions",
            headers=auth_headers,
            params={"page": page, "per_page": per_page},
            timeout=5
        )
        response.raise_for_status()
        sessions = response.json()
    except Exception:
        sessions = {"data": [], "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0}}
    
    return templates.TemplateResponse(
        "account_detail.html",
        {
            "request": request,
            "account": account,
            "cn": cn,  # Передаем cn отдельно для случая когда account пустой
            "sessions": sessions,
            "now": format_datetime(datetime.now(timezone.utc))
        }
    )


# =============================================================================
# Sessions
# =============================================================================

@router.get("/sessions", response_class=HTMLResponse)
def sessions_list(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    account: Optional[str] = None,
    source_ip: Optional[str] = None,
    status: Optional[str] = None,
    country: Optional[str] = None
):
    """
    Журнал сессий.
    
    I8.1: Получаем данные через API (DataTables будет загружать через AJAX)
    
    Архитектура:
    - Сервер НЕ загружает данные, только рендерит пустую таблицу
    - DataTables инициализируется с serverSide: true
    - DataTables загружает данные через AJAX запрос к /api/v1/sessions
    - Пользователь видит "Loading..." пока данные загружаются
    - Результат: одна пагинация, управляемая DataTables
    """
    auth_headers = _get_auth_from_cookie(request)
    
    # Не загружаем данные на сервере - DataTables загрузит через AJAX
    # Передаём только параметры фильтров в шаблон для инициализации DataTables
    sessions = {"data": [], "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0}}
    
    return templates.TemplateResponse(
        "sessions.html",
        {
            "request": request,
            "sessions": sessions,
            "account": account,
            "source_ip": source_ip,
            "status": status,
            "country": country
        }
    )


# =============================================================================
# Attempts
# =============================================================================

@router.get("/attempts", response_class=HTMLResponse)
def attempts_list(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    account: Optional[str] = None,
    source_ip: Optional[str] = None,
    failure_type: Optional[str] = None
):
    """
    Неудачные попытки подключения.
    
    I8.1: Получаем данные через API
    """
    auth_headers = _get_auth_from_cookie(request)
    
    # Формируем параметры запроса
    params = {"page": page, "per_page": per_page}
    if account:
        params["account"] = account
    if source_ip:
        params["source_ip"] = source_ip
    if failure_type:
        params["failure_type"] = failure_type
    
    try:
        response = requests.get(
            "http://127.0.0.1:8000/api/v1/attempts",
            headers=auth_headers,
            params=params,
            timeout=5
        )
        response.raise_for_status()
        attempts = response.json()
    except Exception:
        attempts = {"data": [], "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0}}
    
    return templates.TemplateResponse(
        "attempts.html",
        {
            "request": request,
            "attempts": attempts,
            "account": account,
            "source_ip": source_ip,
            "failure_type": failure_type
        }
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _get_auth_from_cookie(request: Request) -> dict:
    """
    Получает авторизационные заголовки для API запросов.
    
    Поддерживает:
    1. session_id cookie - автоматически передается браузером
    2. Authorization заголовок - для AJAX запросов
    3. auth cookie (old) - backward compatibility
    
    I8.2: Проверка аутентификации.
    
    Returns:
        dict: Заголовки для API запроса
    """
    from web.auth import validate_session
    
    logger.debug(f"[AUTH] _get_auth_from_cookie: проверка авторизации")
    logger.debug(f"[AUTH] Cookies: {list(request.cookies.keys())}")
    
    # Приоритет 1: Session ID из cookie (для веб-интерфейса)
    session_id = request.cookies.get("session_id")
    if session_id:
        logger.debug(f"[AUTH] Найден session_id cookie: {session_id}")
        username = validate_session(session_id)
        if username:
            logger.debug(f"[AUTH] Session валидна, username={username}")
            # Для API запросов используем Basic Auth с учетными данными из конфигурации
            auth_config = get_web_auth_credentials()
            valid_username = auth_config.get("username", "admin")
            valid_password = auth_config.get("password", "admin")
            credentials = base64.b64encode(f"{valid_username}:{valid_password}".encode()).decode()
            logger.debug(f"[AUTH] Возвращаем Authorization заголовок для API запроса")
            return {"Authorization": f"Basic {credentials}"}
        logger.debug(f"[AUTH] Session невалидна")
    
    # Приоритет 2: Authorization заголовок (для AJAX запросов)
    auth_header = request.headers.get("Authorization")
    if auth_header:
        logger.debug(f"[AUTH] Найден Authorization заголовок")
        return {"Authorization": auth_header}
    
    # Приоритет 3: Старый auth cookie (backward compatibility)
    auth_cookie = request.cookies.get("auth")
    if auth_cookie:
        logger.debug(f"[AUTH] Найден старый auth cookie")
        return {"Authorization": f"Basic {auth_cookie}"}
    
    # Если нет авторизации, перенаправляем на login
    logger.warning(f"[AUTH] Нет авторизации, перенаправление на /login")
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": "/login"}
    )
