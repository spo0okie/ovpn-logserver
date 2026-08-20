# REST API

Базовый префикс `/api/v1`. Аутентификация обязательна для всех эндпоинтов, кроме
`/health`: Basic Auth либо cookie-сессия, полученная через `/login`.

Интерактивная схема (`/docs`, `/redoc`, `/openapi.json`) отдаётся **только** при
`debug: true` в `config/web.yaml`; в проде отключена намеренно.

## Эндпоинты

| Метод и путь | Назначение |
|---|---|
| `GET /api/v1/accounts` | список пользователей (агрегирован по CN) |
| `GET /api/v1/accounts/{cn}` | детали пользователя со списком его сертификатов |
| `GET /api/v1/accounts/{cn}/sessions` | сессии пользователя по всем его сертификатам |
| `GET /api/v1/sessions` | журнал сессий |
| `GET /api/v1/sessions/active` | активные сессии |
| `GET /api/v1/sessions/{session_id}` | детали сессии |
| `GET /api/v1/attempts` | неудачные попытки (⚠️ всегда пусто, см. [known-gaps.md](known-gaps.md)) |
| `GET /api/v1/stats/overview` | сводные метрики |
| `GET /api/v1/stats/connections` | подключения по периодам |
| `GET /api/v1/stats/failures` | статистика отказов |
| `GET /api/v1/stats/geography` | распределение по странам |
| `GET /health` | проверка живости, без аутентификации |

## Формат ответов

Списки: `{"data": [...], "meta": {...}}`, где `meta` содержит `page`, `per_page`,
`total`, `total_pages`, а также `sort_by` и `sort_order` там, где сортировка
поддержана.

Ошибки приходят завёрнутыми FastAPI: `{"detail": {"error": "...", "code": "..."}}`.
Используемые коды: `ACCOUNT_NOT_FOUND`, `SESSION_NOT_FOUND`, `INVALID_PARAMETER`.

`GET /api/v1/sessions` дополнительно умеет режим server-side DataTables: при
наличии параметра `draw` принимает `search`, `order_col`, `order_dir` и отвечает
в другом формате — `{"draw", "recordsTotal", "recordsFiltered", "data"}`.

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
can_connect, has_ccd, last_session}`, где каждый элемент `certificates[]` — это
`{id, serial_number, valid_from, valid_to, is_revoked, revoked_at}`.

Фильтры списка: `is_revoked`, `has_ccd`, `search`, плюс `sort_by`
(`cn`, `created_at`, `cert_count`, `active_certs`) и `sort_order`.

⚠️ Семантика `is_revoked` изменилась вместе с моделью: `true` означает «у
пользователя есть хотя бы один отозванный сертификат», а не «пользователь
заблокирован».

В `stats/overview` блок `accounts` содержит `total_users` (уникальные CN) и
`total_certs` (сертификаты) — единого поля `total` нет.

## Известные заглушки

В ответах сессий поля `geo.country_code`, `region`, `latitude`, `longitude`
всегда `None`: таблица `geoip_cache` к сессиям не джойнится, сохраняются только
`country` и `city`. Поля `created_at`/`updated_at` у сессии синтетические
(производные от `connected_at`/`disconnected_at`), а не колонки БД.
