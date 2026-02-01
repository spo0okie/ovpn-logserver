# REST API Design

## Базовый URL

```
/api/v1
```

## Аутентификация

Basic Auth (Authorization: Basic base64(username:password))

## Endpoints

### Accounts

#### GET /api/v1/accounts

Список аккаунтов с фильтрацией и пагинацией.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| is_revoked | bool | Фильтр по статусу отзыва |
| has_ccd | bool | Фильтр по наличию CCD |
| search | string | Поиск по CN |
| page | int | Номер страницы (default: 1) |
| per_page | int | Элементов на страницу (default: 20, max: 100) |

**Response 200:**
```json
{
  "data": [
    {
      "id": 1,
      "cn": "user1",
      "valid_from": "2024-01-01T00:00:00Z",
      "valid_to": "2025-01-01T00:00:00Z",
      "is_revoked": false,
      "has_ccd": true,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 150,
    "total_pages": 8
  }
}
```

#### GET /api/v1/accounts/{cn}

Детальная информация об аккаунте, включая состояние и последнюю сессию.

**Response 200:**
```json
{
  "id": 1,
  "cn": "user1",
  "valid_from": "2024-01-01T00:00:00Z",
  "valid_to": "2025-01-01T00:00:00Z",
  "is_revoked": false,
  "revoked_at": null,
  "has_ccd": true,
  "can_connect": true,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "last_session": {
    "id": 123,
    "status": "active",
    "connected_at": "2024-01-31T10:00:00Z",
    "disconnected_at": null,
    "is_active": true,
    "source_ip": "192.168.1.100",
    "country": "Russia",
    "city": "Moscow"
  }
}
```

**Response 404:**
```json
{
  "error": "Account not found",
  "code": "ACCOUNT_NOT_FOUND"
}
```

#### GET /api/v1/accounts/{cn}/sessions

История сессий аккаунта.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| from | datetime | Начало периода |
| to | datetime | Конец периода |
| status | string | Фильтр по статусу (active, closed) |
| page | int | Номер страницы |
| per_page | int | Элементов на страницу |

**Response 200:**
```json
{
  "data": [
    {
      "id": 123,
      "connected_at": "2024-01-31T10:00:00Z",
      "disconnected_at": null,
      "duration_seconds": null,
      "source_ip": "192.168.1.100",
      "country": "Russia",
      "city": "Moscow",
      "virtual_ip": "10.8.0.5",
      "status": "active",
      "bytes_sent": 1024000,
      "bytes_received": 2048000
    }
  ],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 45
  }
}
```

### Sessions

#### GET /api/v1/sessions

Список всех сессий.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| account | string | Фильтр по CN аккаунта |
| from | datetime | Начало периода |
| to | datetime | Конец периода |
| status | string | Фильтр по статусу |
| source_ip | string | Фильтр по IP |
| country | string | Фильтр по стране |
| page | int | Номер страницы |
| per_page | int | Элементов на страницу |

**Response 200:**
```json
{
  "data": [
    {
      "id": 123,
      "account_cn": "user1",
      "connected_at": "2024-01-31T10:00:00Z",
      "disconnected_at": null,
      "duration_seconds": null,
      "source_ip": "192.168.1.100",
      "geo": {
        "country": "Russia",
        "country_code": "RU",
        "city": "Moscow"
      },
      "virtual_ip": "10.8.0.5",
      "status": "active",
      "bytes_sent": 1024000,
      "bytes_received": 2048000
    }
  ],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 1500
  }
}
```

#### GET /api/v1/sessions/{id}

Детали конкретной сессии.

**Response 200:**
```json
{
  "id": 123,
  "account_cn": "user1",
  "session_id": "vpn-session-abc123",
  "connected_at": "2024-01-31T10:00:00Z",
  "disconnected_at": null,
  "duration_seconds": null,
  "is_active": true,
  "source_ip": "192.168.1.100",
  "geo": {
    "country": "Russia",
    "country_code": "RU",
    "city": "Moscow",
    "region": "Moscow",
    "latitude": 55.7558,
    "longitude": 37.6173
  },
  "virtual_ip": "10.8.0.5",
  "bytes_sent": 1024000,
  "bytes_received": 2048000,
  "status": "active",
  "created_at": "2024-01-31T10:00:00Z",
  "updated_at": "2024-01-31T10:00:00Z"
}
```

#### GET /api/v1/sessions/active

Список активных сессий.

**Response 200:**
```json
{
  "count": 15,
  "data": [
    {
      "id": 123,
      "account_cn": "user1",
      "connected_at": "2024-01-31T10:00:00Z",
      "source_ip": "192.168.1.100",
      "country": "Russia",
      "city": "Moscow",
      "virtual_ip": "10.8.0.5"
    }
  ]
}
```

### Connection Attempts

#### GET /api/v1/attempts

Список неудачных попыток подключения.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| account | string | Фильтр по CN |
| from | datetime | Начало периода |
| to | datetime | Конец периода |
| failure_type | string | Тип ошибки |
| source_ip | string | Фильтр по IP |
| page | int | Номер страницы |
| per_page | int | Элементов на страницу |

**Response 200:**
```json
{
  "data": [
    {
      "id": 456,
      "account": {
        "cn": "user2",
        "prefix": "org_"
      },
      "attempted_at": "2024-01-31T09:30:00Z",
      "source_ip": "10.0.0.50",
      "cert_cn": "user2",
      "failure_reason": "Certificate has been revoked",
      "failure_type": "cert_revoked",
      "details": "CRL check failed"
    }
  ],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 50
  }
}
```

### Statistics

#### GET /api/v1/stats/overview

Общая статистика.

**Response 200:**
```json
{
  "accounts": {
    "total": 150,
    "active_certs": 145,
    "revoked": 5,
    "with_ccd": 140,
    "expiring_soon": 10
  },
  "sessions": {
    "active": 15,
    "today": 45,
    "this_week": 280,
    "this_month": 1200
  },
  "attempts": {
    "failed_today": 5,
    "failed_this_week": 25
  }
}
```

#### GET /api/v1/stats/connections

Статистика подключений по времени.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| from | datetime | Обязательный |
| to | datetime | Обязательный |
| group_by | string | hour, day, week, month (default: day) |

**Response 200:**
```json
{
  "group_by": "day",
  "data": [
    {
      "period": "2024-01-31",
      "connections": 45,
      "unique_accounts": 30,
      "avg_duration_seconds": 3600
    }
  ]
}
```

#### GET /api/v1/stats/failures

Статистика неудачных попыток.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| from | datetime | Обязательный |
| to | datetime | Обязательный |
| group_by | string | type, day, account |

**Response 200:**
```json
{
  "group_by": "type",
  "data": [
    {
      "failure_type": "cert_revoked",
      "count": 15,
      "percentage": 30
    },
    {
      "failure_type": "auth_failed",
      "count": 20,
      "percentage": 40
    },
    {
      "failure_type": "ccd_missing",
      "count": 10,
      "percentage": 20
    },
    {
      "failure_type": "other",
      "count": 5,
      "percentage": 10
    }
  ]
}
```

#### GET /api/v1/stats/geography

Статистика по геолокации.

**Query Parameters:**
| Параметр | Тип | Описание |
|----------|-----|----------|
| from | datetime | Начало периода |
| to | datetime | Конец периода |
| limit | int | Количество стран (default: 10) |

**Response 200:**
```json
{
  "data": [
    {
      "country": "Russia",
      "country_code": "RU",
      "connections": 500,
      "unique_accounts": 80,
      "percentage": 50
    },
    {
      "country": "Germany",
      "country_code": "DE",
      "connections": 200,
      "unique_accounts": 30,
      "percentage": 20
    }
  ]
}
```

## Коды ошибок

| Код | HTTP Status | Описание |
|-----|-------------|----------|
| ACCOUNT_NOT_FOUND | 404 | Аккаунт не найден |
| SESSION_NOT_FOUND | 404 | Сессия не найден |
| INVALID_DATE_FORMAT | 400 | Неверный формат даты |
| INVALID_PARAMETER | 400 | Неверный параметр |
| UNAUTHORIZED | 401 | Не авторизован |
| FORBIDDEN | 403 | Доступ запрещен |
| INTERNAL_ERROR | 500 | Внутренняя ошибка |

## Пагинация

Все списковые endpoints поддерживают пагинацию через query parameters:
- `page` - номер страницы (начиная с 1)
- `per_page` - количество элементов на страницу

Ответ содержит объект `meta` с информацией о пагинации.
