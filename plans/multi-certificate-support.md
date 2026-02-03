# План реализации поддержки нескольких сертификатов на одного пользователя

## Описание задачи

Перестроить архитектуру базы данных и логику работы с аккаунтами для поддержки нескольких сертификатов с одним CN (Common Name).

## Текущая проблема

```
Duplicate entry 'romanov_mv' for key 'accounts.uk_cn'
```

Ошибка возникает при попытке создать второй account с тем же CN.

## Архитектурные изменения

### Новая структура таблицы accounts

```sql
CREATE TABLE accounts (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cn VARCHAR(255) NOT NULL,                    -- без UNIQUE
    serial_number VARCHAR(64) NOT NULL,          -- новое поле
    valid_from DATETIME,
    valid_to DATETIME,
    is_revoked BOOLEAN DEFAULT FALSE,
    revoked_at DATETIME,
    has_ccd BOOLEAN DEFAULT FALSE,
    ccd_updated_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_cn_serial (cn, serial_number), -- composite unique
    INDEX idx_cn (cn),                           -- для поиска по CN
    INDEX idx_serial_number (serial_number)      -- для CRL операций
);
```

### Пример данных

```
| id | cn         | serial_number | is_revoked |
|----|------------|---------------|------------|
| 1  | romanov_mv | 12345ABC      | false      |
| 2  | romanov_mv | 67890DEF      | false      |
| 3  | romanov_mv | 11111FFF      | true       |
```

## План реализации

### 1. Миграция базы данных

**Файл:** `database/migrations/versions/002_add_serial_number.py`

- [ ] Создать новую миграцию (не изменять 001_initial_schema.py)
- [ ] Добавить колонку `serial_number` VARCHAR(64) nullable
- [ ] Заполнить существующие записи значением `CONCAT('legacy_', id)`
- [ ] Сделать колонку NOT NULL
- [ ] Удалить старый constraint `uk_cn`
- [ ] Создать новый composite unique constraint `uk_cn_serial` (cn, serial_number)
- [ ] Создать индексы `idx_cn` и `idx_serial_number`

### 2. Обновление модели Account

**Файл:** `core/models.py`

- [ ] Добавить поле `serial_number: Mapped[str]` с default='unknown'
- [ ] Убрать `UniqueConstraint("cn", name="uk_cn")`
- [ ] Добавить `UniqueConstraint("cn", "serial_number", name="uk_cn_serial")`
- [ ] Обновить docstring модели

### 3. Обновление client_connect.py

**Файл:** `collector/client_connect.py`

- [ ] Обновить `get_env_vars()` для извлечения `tls_serial_0` из переменных окружения
- [ ] Обновить `create_or_get_account(db, cn, serial_number)` для приема serial_number
- [ ] Обновить вызов `create_or_get_account` с передачей serial_number
- [ ] Обновить docstring и комментарии

### 4. Обновление cert_sync.py

**Файл:** `collector/cert_sync.py`

- [ ] Обновить `sync_certificates()` для поиска по (cn, serial_number)
- [ ] Обновить создание Account с serial_number
- [ ] Обновить обновление существующего Account
- [ ] Убедиться что `extract_cert_info` возвращает serial_number

### 5. Обновление crl_checker.py

**Файл:** `collector/crl_checker.py`

- [ ] Обновить `check_crl()` для работы с serial_number из account
- [ ] Убрать `build_cn_to_serial_map` (теперь serial_number в БД)
- [ ] Обновить логику отметки отозванных сертификатов
- [ ] Обновить логику восстановления (unrevoked) сертификатов

### 6. Обновление Web API

**Файл:** `web/api/accounts.py`

- [ ] Обновить `_account_to_list_item()` для включения serial_number
- [ ] Обновить `list_accounts()` для группировки по CN
- [ ] Добавить aggregated поля: cert_count, active_certs, has_active_cert
- [ ] Обновить `get_account()` для возврата списка сертификатов
- [ ] Обновить `get_account_sessions()` для получения сессий по CN
- [ ] Добавить helper `_can_connect_by_cn()` - проверка активности по CN

**Файл:** `web/api/stats.py`

- [ ] Обновить `get_overview_stats()` для группировки по CN
- [ ] Обновить подсчет total_accounts (уникальные CN)
- [ ] Обновить подсчет active_certs (неотозванные сертификаты)

**Файл:** `web/schemas.py`

- [ ] Обновить `AccountListItem` - добавить cert_count, active_certs
- [ ] Обновить `AccountDetail` - добавить список сертификатов
- [ ] Добавить `CertificateItem` схему
- [ ] Обновить `AccountsStats` если нужно

### 7. Обновление Frontend

**Файл:** `web/templates/accounts.html`

- [ ] Обновить таблицу для группировки по CN
- [ ] Добавить колонку "Certificates" с количеством
- [ ] Добавить колонку "Active Certs"
- [ ] Обновить статус (Active если есть хоть один неотозванный)
- [ ] Обновить ссылки на детали пользователя

**Файл:** `web/templates/account_detail.html`

- [ ] Обновить для отображения списка сертификатов
- [ ] Добавить таблицу сертификатов (serial, valid_from, valid_to, status)
- [ ] Обновить отображение сессий (все сессии пользователя по CN)
- [ ] Обновить статус "Can connect"

**Файл:** `web/routes/pages.py`

- [ ] Обновить обработку списка аккаунтов для группировки
- [ ] Обновить детали аккаунта для получения всех сертификатов

### 8. Обновление тестов

**Файл:** `core/tests/test_models.py`

- [ ] Добавить тест создания Account с serial_number
- [ ] Добавить тест unique constraint (cn, serial_number)
- [ ] Добавить тест что можно создать два account с одинаковым cn но разным serial

**Файл:** `collector/tests/test_client_connect.py`

- [ ] Обновить `env` фикстуру для включения serial_number
- [ ] Обновить тесты для проверки serial_number
- [ ] Добавить тест создания двух accounts с одним CN но разным serial

**Файл:** `collector/tests/test_cert_sync.py`

- [ ] Обновить тесты для проверки создания account с serial_number
- [ ] Добавить тест создания двух записей для одного CN с разными serial
- [ ] Обновить `create_test_certificate` для возврата serial

**Файл:** `collector/tests/test_crl_checker.py`

- [ ] Обновить тесты для работы с serial_number из account
- [ ] Убрать тесты для `build_cn_to_serial_map`

**Файл:** `web/tests/test_api.py`

- [ ] Обновить тесты для новой структуры API
- [ ] Добавить тесты группировки по CN
- [ ] Добавить тесты для aggregated stats

**Файл:** `tests/integration/test_full_lifecycle.py`

- [ ] Обновить для поддержки нескольких сертификатов
- [ ] Добавить тест полного lifecycle с multiple certificates

**Файл:** `tests/e2e/test_end_to_end.py`

- [ ] Обновить e2e тесты

### 9. Дополнительные файлы

- [ ] Обновить `database/init.sql` если используется
- [ ] Обновить `docker/mysql/init.sql` если нужно
- [ ] Обновить документацию в `plans/database-schema.md`

## Важные моменты реализации

### OpenVPN переменные окружения

OpenVPN предоставляет serial number в переменной `tls_serial_0` (hex строка).

```python
serial_number = os.environ.get('tls_serial_0', 'unknown')
```

### Группировка по CN

SQL для получения списка пользователей с агрегацией:

```python
from sqlalchemy import func, case

# Группировка по CN
query = db.query(
    Account.cn,
    func.count(Account.id).label('cert_count'),
    func.sum(case((Account.is_revoked == False, 1), else_=0)).label('active_certs'),
    func.max(Account.has_ccd).label('has_ccd'),
).group_by(Account.cn)
```

### Проверка активности пользователя

```python
def can_user_connect(db, cn: str) -> bool:
    """Проверяет может ли пользователь подключаться (есть неотозванный сертификат)."""
    return db.query(Account).filter(
        Account.cn == cn,
        Account.is_revoked == False
    ).first() is not None
```

### Обратная совместимость

При миграции существующих данных:
- Использовать `CONCAT('legacy_', id)` для заполнения serial_number
- Это гарантирует уникальность для существующих записей

## Тестирование

### Сценарии тестирования

1. **Создание двух сертификатов с одним CN**
   - Создать account с CN='test', serial='123'
   - Создать account с CN='test', serial='456'
   - Оба должны существовать без ошибок

2. **Подключение с разных сертификатов**
   - Подключиться с CN='test', serial='123' -> создать сессию
   - Подключиться с CN='test', serial='456' -> создать сессию
   - Две сессии для разных account_id

3. **Отзыв одного сертификата**
   - Отозвать сертификат с serial='123'
   - Пользователь всё ещё активен (есть serial='456')
   - Статистика: 1 отозван, 1 активен

4. **Группировка в UI**
   - Показывать одну строку для CN='test'
   - Cert count = 2
   - Active certs = 1
   - Status = Active

## Последовательность реализации

Рекомендуемый порядок:

1. Миграция БД + Модель (фундамент)
2. Обновление collector скриптов (client_connect, cert_sync, crl_checker)
3. Обновление Web API
4. Обновление Frontend
5. Обновление тестов

Или можно идти файл за файлом с обновлением связанных тестов.
