# =============================================================================
# Dockerfile для Web приложения (FastAPI)
# =============================================================================

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/web /app/web/static /app/core /app/collector /app/database /app/sessions \
    && touch /app/web/static/.keep

# Зависимости устанавливаем из requirements.txt — детерминированно.
COPY web/requirements.txt /tmp/web-requirements.txt
COPY collector/requirements.txt /tmp/collector-requirements.txt
COPY database/requirements.txt /tmp/database-requirements.txt
RUN pip install --no-cache-dir \
        -r /tmp/web-requirements.txt \
        -r /tmp/collector-requirements.txt \
        -r /tmp/database-requirements.txt \
        aiofiles

COPY web/ /app/web/
COPY core/ /app/core/
COPY collector/ /app/collector/
COPY database/ /app/database/
COPY config/ /app/config/

RUN touch /app/__init__.py

# entrypoint накатывает миграции и запускает uvicorn без --reload (это prod).
COPY docker/web/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
