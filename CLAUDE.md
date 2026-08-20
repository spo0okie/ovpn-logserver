# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Проектная документация, комментарии и коммиты — на русском языке.

## Что это

OpenVPN LogServer — пассивный мониторинг OpenVPN-сервера (только наблюдение, никакого управления VPN): журнал сессий с геолокацией, учёт сертификатов/CRL/CCD, REST API + Jinja2 UI. Прод — Linux (Debian) на том же хосте, что и OpenVPN; MySQL 8.0.

## Команды

```bash
# Юнит-тесты по модулям (SQLite, Docker не нужен)
pytest collector/tests web/tests core/tests database/tests

# Интеграционные (SQLite, симуляция VPN-подключений через прямые вызовы hook-функций)
pytest tests/integration

# Один тест
pytest collector/tests/test_cert_sync.py::test_name -v

# E2E — требует Docker; conftest сам поднимает docker-compose (медленно)
pytest tests/e2e

# Web-приложение локально
uvicorn web.main:app --reload

# Docker-стенд (mysql + openvpn-server + web; клиент — profile "client")
cp docker/.env.example docker/.env   # заполнить REPLACE_ME
docker compose -f docker/docker-compose.yml up -d

# Миграции Alembic
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini revision -m "описание"
```

Зависимости раздельные: `web/requirements.txt`, `collector/requirements.txt`, `database/requirements.txt` — для разработки ставить все три.

## Архитектура

Три компонента, общий код в `core/`:

- **`collector/`** — запись данных. Два пути:
  - **Script-hooks** `client_connect.py` / `client_disconnect.py` — вызываются самим OpenVPN на каждое (от)подключение через `client-connect`/`client-disconnect` в server.conf. Читают переменные окружения OpenVPN, пишут в БД.
  - **Периодическая синхронизация** `sync_all.py` (systemd timer `openvpn-sync.timer`) — запускает по порядку: `cert_sync` → `crl_checker` → `ccd_checker` → `session_cleanup`. Порядок важен: cleanup идёт только после успешной синхронизации.
  - `mgmt_client.py` — чтение management-сокета OpenVPN (список живых клиентов для orphan-detection).
- **`core/`** — `models.py` (SQLAlchemy: Account, Session, ConnectionAttempt, GeoIPCache), `database.py` (engine/SessionLocal), `config.py` (загрузка конфигов), `geoip.py` (ip-api.com), `serial.py` (нормализация серийников).
- **`web/`** — FastAPI: `api/{accounts,sessions,stats}.py` (REST под `/api/v1`, Basic Auth через `Depends(get_current_user)`), `routes/pages.py` (HTML-страницы), `auth.py`, `schemas.py`.
- **`database/`** — Alembic (`alembic.ini`, `migrations/`) и `init.sql`.

## Конфигурация

`core/config.py` — единая точка: YAML из `config/*.yaml` (создаются из `*.yaml.example`, в git не коммитятся) + ENV-override поверх. `DATABASE_URL` в ENV перекрывает всё подключение целиком. Fallback на захардкоженные пароли запрещён — при отсутствии обязательных значений приложение падает с `ConfigError`. Конфиг кешируется через `lru_cache` — в тестах после смены ENV вызывать `core.config.reload_config()`.

## Критичные инварианты

- **Hooks не ломают VPN**: `client_connect.py`/`client_disconnect.py` при ЛЮБОЙ ошибке возвращают exit 0. Ненулевой exit из client-connect заблокирует подключение клиента.
- **Серийные номера сертификатов** — всегда через `core.serial.normalize_serial()` (канон — decimal-строка). OpenVPN отдаёт decimal, cryptography — int, старые данные — вперемешку; прямое сравнение без нормализации даёт дубли accounts.
- **Схема БД имеет несколько источников правды**: миграции Alembic (канон), `database/init.sql` и `core/models.py`. Любое изменение схемы — согласованно во всех местах. `docker/mysql/init.sql` таблиц НЕ создаёт (только `ALTER DATABASE`) — иначе конфликт с `alembic upgrade head` и crash-loop web-контейнера.
- **Тесты на SQLite, прод на MySQL**: `client_connect` использует MySQL-специфичный `INSERT ... ON DUPLICATE KEY UPDATE`; SQLite-тесты не ловят UNSIGNED/ENUM/FK-расхождения. E2E в Docker — единственная проверка на реальном MySQL.
- **Время**: в коде исторически смешаны naive `datetime.utcnow()` и aware `datetime.now(timezone.utc)` — сравнение их кидает `TypeError`. При правках придерживаться стиля окружающего кода, отображение — через `web/utils/timezone.py`. Контекст: `docs/timezone.md`.
- **Прямой вызов функций API из UI-роутов**: FastAPI не применяет `Query(...)` — незаданные аргументы приходят объектами `Query`, а не значениями по умолчанию, и попадают в SQL. Передавать все параметры явно (см. `web/routes/pages.py`).
- **Переводы строк**: исполняемые файлы (`collector/openvpn_scripts/*`, `docker/**/entrypoint.sh`) обязаны быть в LF. При CRLF шебанг превращается в `#!/usr/bin/env python3`, интерпретатор не находится, хук возвращает ненулевой код и OpenVPN отказывает клиентам. Защита — `.gitattributes` с `* text=auto eol=lf`; при записи файлов из Python указывать `newline='
'`.
- **Паттерн тестовых conftest**: `DATABASE_URL` и auth-ENV выставляются ДО импорта `web.main`/`core.database`, затем `reload_config()` — иначе закешируется реальный конфиг.

## Документация

`docs/` — проектная документация:

- `invariants.md` — расшифровка кодов `I4.5`, `C1.7`, `M1.4`, `S3.2` из докстрингов. **Читать перед правкой collector'а**: там же обоснование fail-closed-логики очистки сессий.
- `architecture.md` — компоненты, границы модулей, почему хуки вместо разбора логов.
- `database.md` — схема, миграции, расхождение моделей и MySQL-типов.
- `api.md` — контракт REST API (multi-cert: список агрегирован по CN).
- `multi-certificate.md` — модель «строка = сертификат», нормализация серийников, `legacy_*`.
- `openvpn-setup.md` — что обязано быть в `server.conf`, иначе collector молча не собирает данные.
- `deployment.md` — развёртывание и systemd.
- `timezone.md` — naive-UTC в БД, конвертация на границе отображения.
- `known-gaps.md` — что заявлено, но не работает.
- `connection-attempts.md` — почему учёт неудачных попыток не реализован и как его сделать через management-интерфейс.

`tz.md` в корне — исходное ТЗ. `README.md` — точка входа для внешнего читателя.
