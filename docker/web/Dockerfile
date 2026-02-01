# =============================================================================
# Dockerfile для Web приложения (FastAPI)
# =============================================================================
# Создает образ FastAPI приложения с Uvicorn сервером
# =============================================================================

FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Создаем директории для приложения
RUN mkdir -p /app/web /app/core /app/collector /app/database

# Копируем requirements (если есть) или устанавливаем напрямую
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    sqlalchemy \
    pymysql \
    cryptography \
    python-jose[cryptography] \
    passlib[bcrypt] \
    python-multipart \
    jinja2 \
    aiofiles \
    requests

# Копируем код приложения
COPY web/ /app/web/
COPY core/ /app/core/
COPY collector/ /app/collector/
COPY database/ /app/database/

# Создаем пустой __init__.py если отсутствует
RUN touch /app/__init__.py

# Устанавливаем переменные окружения по умолчанию
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Открываем порт
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Запускаем приложение
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
