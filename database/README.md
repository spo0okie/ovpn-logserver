# Database Module

Модуль для управления базой данных OpenVPN Log Server.

## Структура

```
database/
├── alembic.ini              # Конфигурация Alembic
├── migrations/              # Директория с миграциями
│   ├── env.py              # Окружение Alembic
│   ├── script.py.mako      # Шаблон для новых миграций
│   └── versions/           # Директория с версиями миграций
│       └── 001_initial_schema.py  # Начальная миграция
├── tests/                   # Тесты для схемы БД
│   └── test_schema.py      # Тесты инвариантов
└── requirements.txt        # Зависимости
```

## Инварианты схемы

| Инвариант | Описание | Тип теста |
|-----------|----------|-----------|
| I1.1 | Уникальность CN в таблице accounts | Интеграционный |
| I1.2 | Каскадное удаление сессий при удалении аккаунта | Интеграционный |
| I1.3 | Ограничение ENUM для статуса сессий | Модульный (схема) |
| I1.4 | NOT NULL для connected_at | Модульный (схема) |
| I1.5 | Воспроизводимость миграций | Интеграционный |

## Таблицы

### accounts
Справочник аккаунтов OpenVPN.

### sessions
Журнал VPN сессий.

### connection_attempts
Неудачные попытки подключения.

### geoip_cache
Кэш GeoIP данных.

## Использование

### Применение миграций

```bash
cd database
alembic upgrade head
```

### Откат миграций

```bash
alembic downgrade base
```

### Создание новой миграции

```bash
alembic revision -m "описание миграции"
```

### Запуск тестов

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск тестов
pytest database/tests/test_schema.py -v
```

## Переменные окружения

- `DATABASE_URL` - URL подключения к БД для миграций
- `TEST_DB_HOST` - хост тестовой БД (по умолчанию: localhost)
- `TEST_DB_PORT` - порт тестовой БД (по умолчанию: 3306)
- `TEST_DB_USER` - пользователь тестовой БД (по умолчанию: openvpn_user)
- `TEST_DB_PASSWORD` - пароль тестовой БД (по умолчанию: openvpn_password)
- `TEST_DB_NAME` - имя тестовой БД (по умолчанию: openvpn_logs_test)
