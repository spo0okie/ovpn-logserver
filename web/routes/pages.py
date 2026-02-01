"""
HTML endpoints для Web UI.

I8.1: UI использует только REST API (прямых запросов к БД нет)
I8.2: Все страницы требуют аутентификации
"""

import os
import base64
from datetime import datetime
from typing import Optional

import requests
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


router = APIRouter(tags=["pages"])

# Настройка шаблонов Jinja2
templates = Jinja2Templates(directory="web/templates")


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
    
    Использует ту же логику что и API auth.
    """
    api_users = os.getenv("API_USERS", "admin:admin")
    
    valid_users = {}
    for user_pass in api_users.split(","):
        if ":" in user_pass:
            user, pwd = user_pass.split(":", 1)
            valid_users[user] = pwd
    
    if username not in valid_users:
        return False
    
    import secrets
    return secrets.compare_digest(password, valid_users[username])


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
    """Обработка формы входа."""
    if not verify_credentials(username, password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401
        )
    
    # Используем cookie для хранения авторизации
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    response.set_cookie(
        key="auth",
        value=credentials,
        max_age=86400 if remember else 3600,  # 1 день или 1 час
        httponly=True,
        secure=False  # В продакшене установить True
    )
    
    # Также пробуем установить сессию если доступна
    try:
        if "session" in request.scope:
            request.session["user"] = username
            request.session["password"] = password
    except Exception:
        pass
    
    return response


@router.get("/logout")
def logout(request: Request):
    """Выход из системы."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
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
    # Получаем авторизационные заголовки
    auth_headers = _get_auth_from_cookie(request)
    
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
            "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
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
    has_ccd: Optional[str] = None
):
    """
    Список аккаунтов.
    
    I8.1: Получаем данные через API
    """
    auth_headers = _get_auth_from_cookie(request)
    
    # Формируем параметры запроса
    params = {"page": page, "per_page": per_page}
    if search:
        params["search"] = search
    if is_revoked is not None:
        params["is_revoked"] = is_revoked.lower() == "true"
    if has_ccd is not None:
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
        accounts = {"data": [], "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0}}
    
    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "accounts": accounts,
            "search": search,
            "is_revoked": is_revoked,
            "has_ccd": has_ccd,
            "now": datetime.utcnow()
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
            "now": datetime.utcnow()
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
    
    I8.1: Получаем данные через API
    """
    auth_headers = _get_auth_from_cookie(request)
    
    # Формируем параметры запроса
    params = {"page": page, "per_page": per_page}
    if account:
        params["account"] = account
    if source_ip:
        params["source_ip"] = source_ip
    if status:
        params["status"] = status
    if country:
        params["country"] = country
    
    try:
        response = requests.get(
            "http://127.0.0.1:8000/api/v1/sessions",
            headers=auth_headers,
            params=params,
            timeout=5
        )
        response.raise_for_status()
        sessions = response.json()
    except Exception:
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
    Получает авторизационные заголовки из cookie или возвращает пустые.
    
    I8.2: Проверка аутентификации.
    """
    auth_cookie = request.cookies.get("auth")
    
    if auth_cookie:
        return {"Authorization": f"Basic {auth_cookie}"}
    
    # Проверяем заголовок Authorization
    auth_header = request.headers.get("Authorization")
    if auth_header:
        return {"Authorization": auth_header}
    
    # Если нет авторизации, перенаправляем на login
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": "/login"}
    )
