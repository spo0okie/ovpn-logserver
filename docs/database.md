# База данных

## Где искать схему

Канон — **миграции Alembic** (`database/migrations/versions/`). Актуальный DDL
одним куском, со всеми MySQL-специфичными типами, лежит в
[`database/init.sql`](../database/init.sql) — он поддерживается в соответствии с
миграциями и годится для ручного bootstrap без Alembic.

Здесь намеренно нет копии DDL: ещё один источник правды означал бы ещё одно место,
которое рассинхронизируется.

| Источник | Роль |
|---|---|
| `database/migrations/versions/` | **канон**, применяется в проде и Docker |
| `database/init.sql` | полный DDL для ручной установки |
| `core/models.py` | ORM; типы упрощены ради SQLite (см. ниже) |
| `docker/mysql/init.sql` | только `ALTER DATABASE`, таблицы НЕ создаёт |

## Миграции

```bash
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini revision -m "описание"
```

Цепочка: `001_initial_schema` → `002_add_serial_number` → `003_add_query_indexes`
→ `004_drop_connection_attempts` → `005_multisite`.

- **002** — переход на несколько сертификатов: добавляет `accounts.serial_number`,
  удаляет `uk_cn`, создаёт `uk_cn_serial (cn, serial_number)`. Существующие строки
  получают `serial_number = CONCAT('legacy_', id)`. Подробности и подводные камни —
  [multi-certificate.md](multi-certificate.md).
- **003** — индексы под фактические запросы: композитный
  `sessions(status, connected_at)` для `/sessions/active` и `session_cleanup`
  (индекс на `connection_attempts` удалён вместе с таблицей в 004).
- **004** — удаление таблицы `connection_attempts`, см.
  [connection-attempts.md](connection-attempts.md).
- **005** — мультисайт: таблицы `vpn_servers` и `ccd_status`, колонка
  `sessions.server_id` (NULL — legacy до мультисайта), индекс
  `sessions(server_id, status)` под `session_cleanup`. См. [multisite.md](multisite.md).

⚠️ В Docker таблицы создаёт **только** Alembic (entrypoint web-контейнера).
`docker/mysql/init.sql` таблицы не создаёт намеренно: когда он это делал,
миграция 001 падала с «Table already exists» и web уходил в crash-loop.

## Таблицы

- **`accounts`** — сертификаты. Строка = один сертификат, «пользователь» = набор
  строк с одним `cn`.
- **`sessions`** — журнал сессий. FK на `accounts` с `ON DELETE CASCADE`;
  `server_id` — FK на `vpn_servers` с `ON DELETE SET NULL` (NULL — legacy).
  `status`: `active` / `closed` / `error`.
- **`vpn_servers`** — справочник инстансов OpenVPN (мультисайт). Записи создаёт
  collector автоматически по `openvpn.server_name`.
- **`ccd_status`** — per-site наличие CCD: строка = (cn, server) — файл `<cn>`
  есть на этом сервере; файлы `<cn>_OFF` (архив выключенного доступа)
  игнорируются. `accounts.has_ccd` — агрегат из этой таблицы.
- **`geoip_cache`** — кэш геолокации по IP, PK — сам `ip`. Записи с истёкшим
  `expires_at` удаляются при обращении.

## Расхождение моделей и реальных типов

`core/models.py` намеренно объявляет обычный `Integer` там, где в MySQL стоит
`INT UNSIGNED` / `BIGINT UNSIGNED` (функции `get_int_type()`, `get_bigint_type()`).
Причина — совместимость с SQLite, на котором идут тесты: в SQLite autoincrement
работает только с `INTEGER PRIMARY KEY`.

Практические следствия:

- переполнение UNSIGNED и расхождения ENUM/FK **тестами не ловятся** — только на
  реальном MySQL (Docker-стенд);
- `alembic revision --autogenerate` будет предлагать ложные изменения типов;
  правки миграций проверять глазами.

## Каскады

Удаление `accounts` уносит связанные `sessions` (CASCADE). У связи не выставлен `passive_deletes`,
поэтому удаление аккаунта через ORM грузит все его сессии в память и удаляет по
одной — на большой истории это тысячи запросов в одной транзакции. Удаление
напрямую в SQL отрабатывает корректно за счёт FK.
