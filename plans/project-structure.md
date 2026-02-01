# Структура проекта OpenVPN LogServer

## Общая архитектура

```
/opt/openvpn-logserver/
├── collector/              # Python модуль сбора данных
│   ├── __init__.py
│   ├── log_watcher.py      # Демон отслеживания логов OpenVPN
│   ├── cert_sync.py        # Синхронизация сертификатов
│   ├── crl_checker.py      # Проверка CRL
│   ├── ccd_checker.py      # Проверка CCD файлов
│   ├── geoip_resolver.py   # Резолвер геолокации
│   ├── database.py         # Модели и подключение к БД
│   ├── config.py           # Конфигурация
│   └── requirements.txt
├── web/                    # FastAPI Web приложение
│   ├── __init__.py
│   ├── main.py             # Точка входа
│   ├── config.py           # Конфигурация
│   ├── database.py         # Подключение к БД
│   ├── models.py           # SQLAlchemy модели
│   ├── schemas.py          # Pydantic схемы
│   ├── auth.py             # Basic аутентификация
│   ├── api/
│   │   ├── __init__.py
│   │   ├── accounts.py     # Endpoints аккаунтов
│   │   ├── sessions.py     # Endpoints сессий
│   │   └── stats.py        # Endpoints статистики
│   ├── static/             # CSS, JS
│   └── templates/          # Jinja2 шаблоны
│       ├── base.html
│       ├── dashboard.html
│       ├── accounts.html
│       ├── sessions.html
│       └── account_detail.html
├── database/
│   └── migrations/         # Alembic миграции
├── config/
│   ├── collector.yaml      # Конфиг коллектора
│   └── web.yaml            # Конфиг web приложения
├── systemd/
│   ├── openvpn-collector.service
│   ├── openvpn-web.service
│   └── openvpn-sync.timer
└── docs/
    └── api.md              # Документация API
```

## Компоненты системы

### 1. Data Collector

**log_watcher.py** - демон, работающий как systemd service:
- Читает логи OpenVPN в реальном времени (tail -f аналог)
- Парсит события подключения/отключения/ошибок
- Запрашивает геолокацию IP
- Записывает данные в MySQL

**cert_sync.py** - периодическая задача:
- Сканирует директорию clients/<prefix><account>/
- Извлекает данные из сертификатов (OpenSSL)
- Обновляет таблицу accounts

**crl_checker.py** - периодическая задача:
- Парсит файл CRL
- Обновляет статус is_revoked

**ccd_checker.py** - периодическая задача:
- Проверяет наличие файлов в client-config-dir
- Обновляет статус has_ccd

### 2. Web Application (FastAPI)

**Преимущества FastAPI над Yii2:**
- Единый язык с коллектором (Python)
- Автоматическая генерация документации API (/docs)
- Встроенная валидация данных (Pydantic)
- Асинхронная обработка запросов
- Меньше boilerplate кода
- Проще развертывание (один процесс vs PHP-FPM + Nginx)

**Структура:**
- REST API endpoints
- Server-side rendered UI (Jinja2)
- Basic аутентификация
- Подключение к MySQL через SQLAlchemy

### 3. База данных MySQL

**Таблицы:**
- accounts - справочник аккаунтов
- sessions - журнал сессий
- connection_attempts - неудачные попытки
- geoip_cache - кэш геолокации

## Потоки данных

```
OpenVPN Logs ──► log_watcher ──► MySQL ◄────┬──── Web UI
                                              │
Certificates ──► cert_sync ────► MySQL ◄──────┤
                                              ├── REST API
CRL File ──────► crl_checker ──► MySQL ◄──────┤
                                              │
CCD Dir ───────► ccd_checker ──► MySQL ◄──────┘
```

## Зависимости

**Python:**
- fastapi + uvicorn (web)
- sqlalchemy + aiomysql (база данных)
- pydantic (валидация)
- pyopenssl (работа с сертификатами)
- cryptography (CRL парсинг)
- pyyaml (конфигурация)

**Системные:**
- systemd (сервисы)
- nginx (reverse proxy, optional)
- mysql-server
