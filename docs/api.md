# REST API

Базовый префикс `/api/v1`. Аутентификация обязательна для всех эндпоинтов, кроме
`/health`: Basic Auth либо cookie-сессия, полученная через `/login`.

Интерактивная схема (`/docs`, `/redoc`, `/openapi.json`) отдаётся **только** при
`app.debug: true` в `config/web.yaml`; в проде отключена намеренно.

## Эндпоинты

| Метод и путь | Назначение |
|---|---|
| `GET /api/v1/accounts` | список пользователей (агрегирован по CN) |
| `GET /api/v1/accounts/{cn}` | детали пользователя со списком его сертификатов |
| `GET /api/v1/accounts/{cn}/sessions` | сессии пользователя по всем его сертификатам |
| `GET /api/v1/sessions` | журнал сессий |
| `GET /api/v1/sessions/active` | активные сессии |
| `GET /api/v1/sessions/{session_id}` | детали сессии |
| `GET /api/v1/servers` | справочник инстансов OpenVPN (мультисайт) |
| `GET /api/v1/stats/overview` | сводные метрики |
| `GET /api/v1/stats/connections` | подключения по периодам |
| `GET /api/v1/stats/geography` | распределение по странам |
| `GET /health` | проверка живости, без аутентификации |

Вне `/api/v1`, но полезно знать: `GET /sessions/export/csv` — выгрузка журнала
теми же фильтрами, что у `/api/v1/sessions` (`account`, `server`, `source_ip`,
`status`, `country`). Отдаёт `text/csv` с разделителем `;` и BOM, не более 10000
строк, время — в зоне сервера. Это UI-роут: аутентификация та же, формат не
версионируется.

## Параметры

| Эндпоинт | Параметры |
|---|---|
| `/accounts` | `page`, `per_page` (≤100), `search` (по CN), `is_revoked`, `has_ccd`, `sort_by` (`cn`, `created_at`, `cert_count`, `active_certs`, `has_ccd`), `sort_order` (`asc`/`desc`) |
| `/accounts/{cn}/sessions` | `page`, `per_page` (≤100), `from`, `to`, `status` |
| `/sessions` | `page`, `per_page` (≤100), `account`, `server`, `from`, `to`, `status`, `source_ip`, `country` (подстрока), плюс DataTables-параметры ниже |
| `/sessions/active` | нет |
| `/stats/overview` | нет |
| `/stats/connections` | `from` и `to` — **обязательны**; `group_by` = `hour`/`day`/`week`/`month` (по умолчанию `day`) |
| `/stats/geography` | `from`, `to`, `limit` (1–100, по умолчанию 10) |

Значения `status` — `active`, `closed`, `error` (`error` = сессия оборвалась,
отключение не зафиксировано). Даты `from`/`to` — ISO-8601, сравниваются с
`connected_at` в **UTC**.

Неизвестный `sort_by` даёт 400 `INVALID_PARAMETER`; неизвестный `sort_order`
молча трактуется как `asc`. Неизвестный `group_by` — 400.

## Формат ответов

Пагинированные списки (`/accounts`, `/accounts/{cn}/sessions`, `/sessions`):
`{"data": [...], "meta": {...}}`, где `meta` содержит `page`, `per_page`,
`total`, `total_pages`, а также `sort_by` и `sort_order` там, где сортировка
поддержана. Исключения — списки без пагинации:

| Эндпоинт | Ответ |
|---|---|
| `/sessions/active` | `{"count", "data"}` |
| `/servers` | `{"data"}` |
| `/stats/connections` | `{"group_by", "data"}` |
| `/stats/geography` | `{"data"}` |
| `/stats/overview` | объект `{"accounts": {...}, "sessions": {...}}` |

Форматов ошибок три, и это важно для клиентов:

| Случай | Тело |
|---|---|
| 400 и 404 из кода | `{"detail": {"error": "...", "code": "..."}}`, коды `ACCOUNT_NOT_FOUND`, `SESSION_NOT_FOUND`, `INVALID_PARAMETER` |
| 401 (нет или неверная аутентификация) | `{"detail": "Authentication required"}` — строкой, а не объектом |
| 422 (валидация параметров FastAPI: `per_page>100`, нет обязательного `from`/`to`, нечисловой `limit`) | стандартный ответ FastAPI со списком `detail[]` |

`GET /api/v1/sessions` дополнительно умеет режим server-side DataTables:
`search`, `order_col`, `order_dir` применяются **всегда**, а `draw` только
меняет формат ответа на `{"draw", "recordsTotal", "recordsFiltered", "data"}`
(оба счётчика равны количеству записей после фильтров). `search` ищет по CN,
имени сервера, source_ip, virtual_ip, стране и городу. `order_col` — номер
колонки таблицы UI, а не имя поля: 0 id, 1 account, 2 server, 3 connected,
4 duration (вычисляемое — сортируется по `connected_at desc`), 5 source_ip,
6 country, 7 virtual_ip, 8 status.

Мультисайт: элементы сессий (список, active, детали, сессии аккаунта, а также
`last_session` в деталях аккаунта) содержат `server_name` (`null` —
legacy-сессии до мультисайта); `GET /api/v1/sessions` принимает фильтр
`server=<name>`. Отобрать только legacy-сессии через `server=` нельзя.

## Контракт аккаунтов

Модель — «одна строка = один сертификат», поэтому список **агрегирован по CN**
(подробности — [multi-certificate.md](multi-certificate.md)).

`GET /accounts` возвращает элементы вида:

```json
{
  "cn": "user_name",
  "cert_count": 2,
  "active_certs": 1,
  "has_active_cert": true,
  "has_ccd": true,
  "created_at": "2026-01-15T10:00:00"
}
```

Полей `id`, `valid_from`, `valid_to`, `is_revoked` на верхнем уровне **нет** —
они относятся к сертификату, а не к пользователю. Ключ детальной страницы — `cn`.

`GET /accounts/{cn}` возвращает `{cn, certificates[], cert_count, active_certs,
can_connect, has_ccd, ccd_sites[], last_session}`, где каждый элемент
`certificates[]` — это `{id, serial_number, valid_from, valid_to, is_revoked,
revoked_at}`, а `ccd_sites[]` — на каких серверах у CN есть CCD-файл (мультисайт):
`{server_name, ccd_updated_at}`; `has_ccd` на верхнем уровне — агрегат
«есть хотя бы на одном сервере».

⚠️ Семантика `is_revoked` изменилась вместе с моделью: `true` означает «у
пользователя есть хотя бы один отозванный сертификат», а не «пользователь
заблокирован».

`last_session` — это `{id, server_name, status, connected_at, disconnected_at,
is_active, source_ip, country, city}`.

В `stats/overview` блок `accounts` содержит `total_users` (уникальные CN),
`total_certs` (сертификаты), `active_certs`, `revoked`, `with_ccd`,
`expiring_soon` — единого поля `total` нет; блок `sessions` — `active`,
`today`, `this_week`, `this_month`.

⚠️ `active_certs` считается по-разному: в `stats/overview` это «не отозван»
(истёкшие тоже попадают), в `/accounts` и `/accounts/{cn}` — «не отозван **и**
не истёк». Совпадать значения не обязаны.

## Известные заглушки

В ответах сессий поля `geo.country_code`, `region`, `latitude`, `longitude`
всегда `None`: таблица `geoip_cache` к сессиям не джойнится, сохраняются только
`country` и `city`. В `/sessions/active` и `/accounts/{cn}/sessions` объекта
`geo` нет вовсе — `country` и `city` лежат плоско. `country_code` в
`stats/geography` тоже всегда `null`.

Поля `created_at`/`updated_at` у сессии синтетические (производные от
`connected_at`/`disconnected_at`), а не колонки БД.

Элементы `/sessions` дополнительно содержат `connected_at_local` и
`disconnected_at_local` — те же моменты, уже отформатированные в зоне сервера
для таблицы UI (см. [timezone.md](timezone.md)).
