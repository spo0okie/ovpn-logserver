"""
HTML endpoints для Web UI.

UI вызывает функции API напрямую (без self-HTTP).
Все страницы требуют аутентификацию: либо session_id cookie, либо Basic Auth.
При отсутствии аутентификации — редирект на /login.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from web.api import accounts as accounts_api
from web.api import attempts as attempts_api
from web.api import sessions as sessions_api
from web.api import stats as stats_api
from web.auth import (
    create_session,
    delete_session,
    get_current_user,
    verify_credentials,
)
from web.dependencies import get_db
from web.utils.timezone import format_datetime

logger = logging.getLogger(__name__)

# secure-флаг session-cookie: за HTTPS в проде выставить SESSION_COOKIE_SECURE=true.
_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
_REMEMBER_LIFETIME = 86400   # 24 часа
_DEFAULT_LIFETIME = 3600     # 1 час
# Верхняя граница размера страницы — совпадает с Query(le=100) в API; здесь
# нужна отдельно, т.к. UI-роуты зовут функции API напрямую, минуя валидацию FastAPI.
_MAX_PER_PAGE = 100


def _clamp_pagination(page: int, per_page: int) -> tuple:
    """Ограничивает page/per_page (UI-роуты обходят Query-валидацию API)."""
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = 20
    per_page = max(1, min(per_page, _MAX_PER_PAGE))
    return page, per_page


router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="web/templates")
templates.env.filters["local_datetime"] = format_datetime


def web_user(request: Request) -> str:
    """
    Аутентификация для UI: при 401 редиректит на /login вместо 401-ответа.
    """
    try:
        return get_current_user(request)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"},
            )
        raise


def _now_local() -> str:
    return format_datetime(datetime.now(timezone.utc))


# =============================================================================
# Auth pages
# =============================================================================


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": error}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember: bool = Form(False),
):
    if not verify_credentials(username, password):
        logger.warning("[LOGIN] Неверные учетные данные: username=%s", username)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    lifetime = _REMEMBER_LIFETIME if remember else _DEFAULT_LIFETIME
    session_id = create_session(username, lifetime_seconds=lifetime)
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=lifetime,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,  # SESSION_COOKIE_SECURE=true за HTTPS в проде
    )
    logger.info("[LOGIN] Успешный вход: username=%s", username)
    return response


@router.get("/logout")
def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_session(session_id)
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_id")
    return response


# =============================================================================
# Dashboard
# =============================================================================


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    _user: str = Depends(web_user),
    db: Session = Depends(get_db),
):
    stats = stats_api.get_overview_stats(db=db)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats, "now": _now_local()},
    )


# =============================================================================
# Accounts
# =============================================================================


def _parse_optional_bool(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    return value.lower() == "true"


@router.get("/accounts", response_class=HTMLResponse)
def accounts_list(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    is_revoked: Optional[str] = None,
    has_ccd: Optional[str] = None,
    sort_by: str = "cn",
    sort_order: str = "asc",
    _user: str = Depends(web_user),
    db: Session = Depends(get_db),
):
    page, per_page = _clamp_pagination(page, per_page)
    accounts = accounts_api.list_accounts(
        page=page,
        per_page=per_page,
        is_revoked=_parse_optional_bool(is_revoked),
        has_ccd=_parse_optional_bool(has_ccd),
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        db=db,
    )
    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "accounts": accounts,
            "search": search,
            "is_revoked": is_revoked,
            "has_ccd": has_ccd,
            "now": _now_local(),
        },
    )


@router.get("/accounts/{cn}", response_class=HTMLResponse)
def account_detail(
    request: Request,
    cn: str,
    page: int = 1,
    per_page: int = 10,
    _user: str = Depends(web_user),
    db: Session = Depends(get_db),
):
    page, per_page = _clamp_pagination(page, per_page)
    try:
        account = accounts_api.get_account(cn=cn, db=db)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        account = {}

    try:
        # ВАЖНО: передаём ВСЕ параметры явно. При прямом вызове функции API
        # (минуя FastAPI) незаданные аргументы получают объекты Query(...),
        # а не None — они попадают в SQL и роняют страницу (TypeError).
        sessions = accounts_api.get_account_sessions(
            cn=cn,
            page=page,
            per_page=per_page,
            from_date=None,
            to_date=None,
            status=None,
            db=db,
        )
    except HTTPException:
        sessions = {
            "data": [],
            "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0},
        }

    return templates.TemplateResponse(
        "account_detail.html",
        {
            "request": request,
            "account": account,
            "cn": cn,
            "sessions": sessions,
            "now": _now_local(),
        },
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
    country: Optional[str] = None,
    _user: str = Depends(web_user),
):
    """
    Сервер не загружает данные — DataTables подтянет их через AJAX
    к /api/v1/sessions. Здесь только рендер шаблона.
    """
    page, per_page = _clamp_pagination(page, per_page)
    return templates.TemplateResponse(
        "sessions.html",
        {
            "request": request,
            "sessions": {
                "data": [],
                "meta": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 0},
            },
            "account": account,
            "source_ip": source_ip,
            "status": status,
            "country": country,
        },
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
    failure_type: Optional[str] = None,
    _user: str = Depends(web_user),
    db: Session = Depends(get_db),
):
    page, per_page = _clamp_pagination(page, per_page)
    attempts = attempts_api.list_attempts(
        page=page,
        per_page=per_page,
        account=account,
        from_date=None,
        to_date=None,
        failure_type=failure_type,
        source_ip=source_ip,
        db=db,
    )
    return templates.TemplateResponse(
        "attempts.html",
        {
            "request": request,
            "attempts": attempts,
            "account": account,
            "source_ip": source_ip,
            "failure_type": failure_type,
        },
    )
