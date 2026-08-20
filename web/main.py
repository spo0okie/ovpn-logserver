"""
Точка входа FastAPI приложения.
"""

import logging
import os
from typing import List

import yaml
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.api import accounts, sessions, stats
from web.auth import get_current_user
from web.routes import pages_router

logger = logging.getLogger(__name__)


def _load_web_config() -> dict:
    """Загружает config/web.yaml с ENV-override."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "web.yaml"
    )
    cfg: dict = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    return cfg


_cfg = _load_web_config()
_app_cfg = _cfg.get("app", {}) or {}
_cors_cfg = _cfg.get("cors", {}) or {}

DEBUG = bool(_app_cfg.get("debug", False))


def _cors_origins() -> List[str]:
    env = os.getenv("CORS_ALLOW_ORIGINS")
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    origins = _cors_cfg.get("allow_origins", [])
    if origins == ["*"]:
        # ["*"] вместе с credentials невалиден — отключаем CORS целиком.
        logger.warning(
            "[CORS] allow_origins=['*'] небезопасен с credentials; CORS отключен."
        )
        return []
    return list(origins)


app = FastAPI(
    title="OpenVPN LogServer API",
    description="REST API для мониторинга OpenVPN подключений",
    version="1.0.0",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
    openapi_url="/openapi.json" if DEBUG else None,
)

_origins = _cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=_cors_cfg.get("allow_methods", ["GET", "POST"]),
        allow_headers=_cors_cfg.get("allow_headers", ["*"]),
    )

app.mount("/static", StaticFiles(directory="web/static"), name="static")

app.include_router(
    accounts.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    sessions.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    stats.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(pages_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
