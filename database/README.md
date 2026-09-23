# Модуль database

Миграции Alembic и DDL для ручной установки. Описание схемы, таблиц и
подводных камней — в [docs/database.md](../docs/database.md). Здесь описание
намеренно не дублируется: каждая копия схемы — ещё одно место, которое
расходится с кодом.

## Состав

```
database/
├── alembic.ini              # script_location = %(here)s/migrations
├── migrations/
│   ├── env.py               # URL БД берётся из core.config
│   └── versions/            # 001 … 005, канон схемы
├── init.sql                 # полный DDL на ревизии 005 для bootstrap без Alembic
├── requirements.txt         # alembic, sqlalchemy, pymysql
└── tests/test_schema.py     # проверки на живом MySQL
```

## Подключение к БД

Alembic берёт подключение из конфигурации приложения (`core/config.py`), а не
из `alembic.ini`: `config/database.yaml`, переменные `DB_*` или целиком
`DATABASE_URL`. Ключи и приоритеты — [config/README.md](../config/README.md).

## Команды

Из корня проекта:

```bash
alembic -c database/alembic.ini upgrade head     # применить все миграции
alembic -c database/alembic.ini current          # текущая ревизия (ожидается 005 (head))
alembic -c database/alembic.ini history          # цепочка ревизий
alembic -c database/alembic.ini downgrade -1     # откат на одну ревизию
alembic -c database/alembic.ini revision -m "описание"
```

То же из каталога `database/` — без `-c`: `cd database && alembic upgrade head`.
Сочетание `-c database/alembic.ini` **изнутри** `database/` — ошибка: такого
пути там нет, и alembic молча читает пустой конфиг
(`No 'script_location' key found`).

В проде запускайте интерпретатором venv, чтобы взялись зафиксированные версии:
`venv/bin/python -m alembic -c database/alembic.ini upgrade head`.

`revision --autogenerate` работает (модели подключены в `env.py`), но из-за
упрощённых ради SQLite типов в `core/models.py` предлагает ложные изменения —
сгенерированную миграцию проверяйте глазами, см. docs/database.md.

## Ручной bootstrap через init.sql

`init.sql` создаёт базу, пользователя и все таблицы на ревизии 005, но **не**
заполняет `alembic_version`. Без отметки следующий `upgrade head` попытается
применить 001 и упадёт на «Table already exists». Поэтому сразу после
`init.sql`:

```bash
alembic -c database/alembic.ini stamp head
```

## Тесты

`tests/test_schema.py` работает только с живым MySQL — SQLite не проверяет
UNSIGNED, ENUM и поведение внешних ключей. Прямые проверки подключаются через
`TEST_DB_HOST`, `TEST_DB_PORT`, `TEST_DB_NAME`, `TEST_DB_USER`,
`TEST_DB_PASSWORD`. Тесты воспроизводимости миграций запускают `alembic`
подпроцессом, а он берёт БД из конфигурации приложения. Поэтому
`DATABASE_URL` должен указывать на ту же тестовую базу (так настроен CI,
`.github/workflows/tests.yml`).

```bash
pytest database/tests
```

Тест воспроизводимости откатывает схему до `base` и накатывает заново —
запускайте его только на тестовой базе.
