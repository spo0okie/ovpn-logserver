# План: Обнаружение и очистка orphaned-сессий

## 1. Архитектурные инварианты системы (из документации)

### 1.1 API-контракты

| Компонент | Контракт |
|-----------|----------|
| `web/api/sessions.py` | REST API: `GET /api/v1/sessions`, `GET /api/v1/sessions/{id}` |
| `web/schemas.py` | Pydantic схемы для валидации |
| `core/models.py` | `Session.status`: enum('active', 'closed', 'error') |

### 1.2 Границы модулей

| Модуль | Ответственность |
|--------|-----------------|
| `collector/` | Скрипты подключения/отключения, sync-задачи |
| `core/` | Модели БД, конфигурация, GeoIP |
| `web/` | FastAPI приложение, REST API |
| `database/` | SQLAlchemy миграции |

### 1.3 Ответственность компонентов

| Компонент | Ответственность |
|-----------|-----------------|
| `client_connect.py` | Создание сессии `status='active'` при подключении |
| `client_disconnect.py` | Обновление сессии `status='closed'` при отключении |
| `sync_all.py` | Периодический запуск cert_sync, crl_checker, ccd_checker |
| OpenVPN Management Interface | Real-time список активных клиентов |

### 1.4 Форматы данных

```python
# Session model (core/models.py)
Session.status: Enum['active', 'closed', 'error']
Session.connected_at: DateTime  # NOT NULL
Session.disconnected_at: DateTime  # NULLABLE
```

## 2. Инварианты среды разработки

- **Изоляция**: Код выполняется исключительно внутри Docker-контейнеров
- **Хост-система**: Не используется как среда исполнения
- **Файловая система**: Доступ к данным хоста запрещён, кроме явно разрешённых volume
- **Volume**: Определяются в `docker-compose.yml`
- **Восстановление**: Предполагается через git

## 3. Фазы реализации

---

### Этап 1: Management Interface - базовая интеграция

**Цель:**
Добавить возможность получения списка активных клиентов через OpenVPN Management Interface без изменения схемы БД.

**Инварианты (новые):**
| Инвариант | Описание |
|-----------|----------|
| M1.1 | `collector/mgmt_client.py` создаёт модуль для работы с Management Interface |
| M1.2 | Модуль не зависит от конкретного пути сокета (читает из конфигурации) |
| M1.3 | Модуль возвращает `Set[str]` - множество CN активных клиентов |
| M1.4 | При недоступности сокета возвращает пустое множество (graceful degradation) |

**Инварианты (унаследованные):**
| Инвариант | Источник |
|-----------|----------|
| I2.1 | `core/database.py`: Base = declarative_base() |
| I4.1-I4.6 | `client_connect.py`: Только переменные окружения, exit 0 при ошибках |
| I5.1-I5.6 | `client_disconnect.py`: Только UPDATE операции |

**Тесты:**
| Инвариант | Тип теста | Предотвращает |
|-----------|-----------|---------------|
| M1.1 | Unit test | Создание модуля без тестов |
| M1.2 | Integration test | HARDCODED_PATH_TO_SOCKET |
| M1.3 | Unit test | Возврат неверного типа данных |
| M1.4 | Integration test | Exception при недоступном сокете |

**Условия перехода к следующему этапу:**
- [ ] Все тесты этапа проходят
- [ ] Модуль `mgmt_client.py` импортируется без ошибок
- [ ] Тест с mock-сокетом возвращает корректное множество CN

**Исполнение:**
- Контейнер: `docker-compose run --rm web` (Python environment)
- Ресурсы: `PYTHONPATH=/app`, доступ на чтение `docker/openvpn-server/`

---

### Этап 2: Session Cleanup - обнаружение orphaned-сессий

**Цель:**
Создать скрипт `session_cleanup.py`, который сравнивает активные сессии в БД со списком из Management Interface.

**Инварианты (новые):**
| Инвариант | Описание |
|-----------|----------|
| C1.1 | `session_cleanup.py` находит все сессии `status='active'` |
| C1.2 | Для каждой активной сессии проверяет наличие CN в Management Interface |
| C1.3 | Сессия помечается как `status='error'` если CN отсутствует в mgmt |
| C1.4 | Устанавливает `disconnected_at = NOW()` для orphaned сессий |
| C1.5 | Логирует каждую orphaned сессию с CN и session_id |
| C1.6 | Функция `cleanup_orphaned_sessions()` идемпотентна |

**Инварианты (унаследованные):**
| Инвариант | Источник |
|-----------|----------|
| M1.1-M1.4 | Из этапа 1 |
| I6.4 | `cert_sync.py`: Идемпотентность операций |

**Тесты:**
| Инвариант | Тип теста | Предотвращает |
|-----------|-----------|---------------|
| C1.1 | Unit test | Пропуск активных сессий |
| C1.2 | Unit test | Неправильная логика сравнения |
| C1.3 | Integration test | Изменение статуса не orphaned сессии |
| C1.4 | Integration test | Отсутствие времени отключения |
| C1.5 | Unit test | Потеря информации об orphaned сессиях |
| C1.6 | Property test | Повреждение данных при повторном запуске |

**Условия перехода к следующему этапу:**
- [ ] Все тесты этапа проходят
- [ ] Скрипт запускается и не падает на пустой БД
- [ ] Созданы интеграционные тесты с SQLite

**Исполнение:**
- Контейнер: `docker-compose run --rm web` (Python environment)
- Ресурсы: `PYTHONPATH=/app`, доступ к SQLite тестовой БД

---

### Этап 3: Интеграция в sync_all.py

**Цель:**
Добавить вызов `session_cleanup` в существующий `sync_all.py`.

**Инварианты (новые):**
| Инвариант | Описание |
|-----------|----------|
| S1.1 | `sync_all.py` вызывает cleanup после других sync-задач |
| S1.2 | Статистика cleanup логируется в том же формате, что и другие задачи |
| S1.3 | Ошибка в cleanup не прерывает выполнение sync_all |

**Инварианты (унаследованные):**
| Инвариант | Источник |
|-----------|----------|
| C1.1-C1.6 | Из этапа 2 |
| I6.1-I6.5 | `sync_all.py`: Порядок выполнения задач |

**Тесты:**
| Инвариант | Тип теста | Предотвращает |
|-----------|-----------|---------------|
| S1.1 | Integration test | Пропуск вызова cleanup |
| S1.2 | Unit test | Inconsistent логирование |
| S1.3 | Integration test | Cascade failure при ошибке cleanup |

**Условия перехода к следующему этапу:**
- [ ] Все тесты этапа проходят
- [ ] `python collector/sync_all.py` выполняется без ошибок
- [ ] В выводе присутствует статистика cleanup

**Исполнение:**
- Контейнер: `docker-compose run --rm web` (Python environment)
- Ресурсы: `PYTHONPATH=/app`, переменные окружения из `.env`

---

### Этап 4: OpenVPN Server - конфигурация Management Interface

**Цель:**
Настроить OpenVPN для работы с Management Interface.

**Инварианты (новые):**
| Инвариант | Описание |
|-----------|----------|
| O1.1 | `docker/openvpn-server/server.conf` содержит директиву `management` |
| O1.2 | Management socket создаётся в `/var/run/openvpn/mgmt.sock` |
| O1.3 | Docker volume для директории сокета |
| O1.4 | `socat` установлен в образе для тестирования |

**Инварианты (унаследованные):**
| Инвариант | Источник |
|-----------|----------|
| I9.1-I9.5 | `docker-compose.yml`: Инварианты развёртывания |

**Тесты:**
| Инвариант | Тип теста | Предотвращает |
|-----------|-----------|---------------|
| O1.1 | Lint test | Отсутствие management директивы |
| O1.2 | Docker test | Сокет недоступен после запуска |
| O1.3 | Docker test | Volume не проброшен |
| O1.4 | Build test | socat не установлен |

**Условия перехода к следующему этапу:**
- [ ] `docker-compose build openvpn-server` успешен
- [ ] `docker-compose up -d openvpn-server` создаёт сокет
- [ ] `docker exec openvpn-server ls /var/run/openvpn/mgmt.sock` возвращает 0

**Исполнение:**
- Контейнер: `docker-compose build/run openvpn-server`
- Ресурсы: NET_ADMIN capability, volume `openvpn_pki`

---

### Этап 5: client_connect.py - обнаружение orphaned при реконнекте

**Цель:**
Добавить проверку orphaned сессий в `client_connect.py` при повторном подключении того же клиента.

**Инварианты (новые):**
| Инвариант | Описание |
|-----------|----------|
| R1.1 | При подключении клиента проверяется наличие `status='active'` сессии того же account |
| R1.2 | Если orphaned сессия найдена - она помечается как `status='error'` |
| R1.3 | Новая сессия создаётся с `status='active'` после закрытия orphaned |
| R1.4 | Все операции происходят в рамках одной транзакции |

**Инварианты (унаследованные):**
| Инвариант | Источник |
|-----------|----------|
| I4.1-I4.6 | `client_connect.py`: exit 0 при любых ошибках |

**Тесты:**
| Инвариант | Тип теста | Предотвращает |
|-----------|-----------|---------------|
| R1.1 | Unit test | Пропуск orphaned сессии при реконнекте |
| R1.2 | Integration test | Orphaned сессия не закрывается |
| R1.3 | Integration test | Дублирование сессий |
| R1.4 | Unit test | Partial update при ошибке |

**Условия перехода к следующему этапу:**
- [ ] Все тесты этапа проходят
- [ ] Тест: два подключения одного CN создают две разные сессии
- [ ] Тест: между сессиями первая помечается как `error`

**Исполнение:**
- Контейнер: `docker-compose run --rm web` (Python environment)
- Ресурсы: `PYTHONPATH=/app`

---

### Этап 6: E2E тестирование в Docker

**Цель:**
Создать интеграционные тесты, проверяющие полный цикл обнаружения orphaned-сессий.

**Инварианты (новые):**
| Инвариант | Описание |
|-----------|----------|
| E1.1 | Docker-compose поднимает все сервисы |
| E1.2 | Подключение клиента создаёт сессию `status='active'` |
| E1.3 | Остановка OpenVPN (kill) помечает активные сессии как `error` |
| E1.4 | Запуск cleanup скрипта обнаруживает orphaned сессии |
| E1.5 | Повторный запуск cleanup не меняет уже закрытые сессии |

**Инварианты (унаследованные):**
| Инвариант | Источник |
|-----------|----------|
| I9.1-I9.5 | Полный набор из docker-compose.yml |

**Тесты:**
| Инвариант | Тип теста | Предотвращает |
|-----------|-----------|---------------|
| E1.1 | Docker test | Сервисы не поднимаются |
| E1.2 | E2E test | Сессия не создаётся |
| E1.3 | Resilience test | Orphaned не обнаруживаются |
| E1.4 | Integration test | Cleanup не работает |
| E1.5 | Regression test | Двойное закрытие сессий |

**Условия перехода к завершению:**
- [x] Все тесты проходят
- [x] `docker-compose up -d` работает
- [x] Логи подтверждают корректное обнаружение orphaned

**Исполнение:**
- Контейнеры: `docker-compose` (mysql, openvpn-server, web)
- Ресурсы: Полная сеть `openvpn-network`, volumes

---

## 4. Сводная таблица зависимостей этапов

```
Этап 1 ──► Этап 2 ──► Этап 3 ──► Этап 6
    │          │          │
    │          │          ▼
    │          │      Этап 4 ──► (обратная связь в Этап 6)
    │          │
    ▼          ▼
Этап 5 ◄─────┘
```

## 5. Контроль архитектурных конфликтов

| Этап | Конфликт | Разрешение |
|------|----------|------------|
| 2 | Требование idempotency vs обнаружение orphaned | Cleanup идемпотентен: повторный запуск не меняет `error` → `error` |
| 4 | Docker volume для сокета vs host access | Volume определён в docker-compose, не требует host access |
| 5 | client_connect exit 0 vs обнаружение orphaned | Обнаружение orphaned часть normal flow, не error |

## 6. Файлы для создания/изменения

| Этап | Файл | Действие |
|------|------|----------|
| 1 | `collector/mgmt_client.py` | Создать |
| 1 | `collector/tests/test_mgmt_client.py` | Создать |
| 2 | `collector/session_cleanup.py` | Создать |
| 2 | `collector/tests/test_session_cleanup.py` | Создать |
| 3 | `collector/sync_all.py` | Изменить |
| 4 | `docker/openvpn-server/server.conf` | Изменить |
| 4 | `docker/openvpn-server/Dockerfile` | Изменить |
| 4 | `docker/openvpn-server/entrypoint.sh` | Изменить |
| 5 | `collector/client_connect.py` | Изменить |
| 5 | `collector/tests/test_client_connect.py` | Изменить |
| 6 | `tests/e2e/test_session_cleanup_e2e.py` | Создать |
| 6 | `docker-compose.yml` | Изменить (опционально) |
