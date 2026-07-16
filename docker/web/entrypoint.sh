#!/bin/sh
set -eu

# Ждём, пока MySQL станет доступным.
if [ -n "${DATABASE_URL:-}" ] || [ -n "${DB_HOST:-}" ]; then
    echo "[entrypoint] applying alembic migrations..."
    cd /app/database
    alembic upgrade head
    cd /app
fi

exec "$@"
