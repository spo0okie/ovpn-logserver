"""
Точка входа FastAPI приложения.

Собирает все endpoints и настраивает приложение.
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.api import accounts, sessions, attempts, stats
from web.auth import get_current_user
from web.routes import pages_router


# Создаем FastAPI приложение
app = FastAPI(
    title="OpenVPN LogServer API",
    description="REST API для мониторинга OpenVPN подключений",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем статические файлы
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Подключаем роутеры с префиксом /api/v1
# I7.6: Все endpoints требуют аутентификацию через Depends(get_current_user)
app.include_router(
    accounts.router,
    prefix="/api/v1",
    dependencies=[Depends(get_current_user)]
)
app.include_router(
    sessions.router,
    prefix="/api/v1",
    dependencies=[Depends(get_current_user)]
)
app.include_router(
    attempts.router,
    prefix="/api/v1",
    dependencies=[Depends(get_current_user)]
)
app.include_router(
    stats.router,
    prefix="/api/v1",
    dependencies=[Depends(get_current_user)]
)

# Подключаем UI роутеры (HTML страницы)
# I8.1: UI использует только REST API
app.include_router(pages_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
