# Поэтапный план разработки OpenVPN LogServer

## Ключевые архитектурные инварианты системы

### API-контракты
- REST API версионирован (`/api/v1/`)
- Все ответы в формате JSON с кодом HTTP статуса
- Пагинация через `page`/`per_page`, мета-информация в `meta`
- Аутентификация: Basic Auth

### Границы модулей
- **Collector** (скрипты) - только запись в БД, никакого чтения
- **Web API** - только чтение из БД, никакой записи
- **Database** - единственное хранилище состояния

### Ответственность компонентов
- `client-connect` - создание записи сессии при подключении
- `client-disconnect` - обновление сессии при отключении
- `cert_sync` - синхронизация сроков сертификатов
- `crl_checker` - проверка отозванных сертификатов
- `ccd_checker` - проверка наличия CCD файлов
- `web API` - предоставление данных для UI и внешних клиентов

### Форматы данных
- Даты в ISO 8601 (UTC)
- IP адреса в строковом виде (IPv4/IPv6)
- Статусы сессий: `active`, `closed`
- Типы ошибок: `auth_failed`, `cert_revoked`, `cert_expired`, `ccd_missing`, `tls_error`, `other`

---

## Этап 1: База данных и миграции

### Цель
Создать структуру БД с гарантией целостности данных на уровне схемы.

### Инварианты
1. **I1.1** - Таблица `accounts` имеет уникальный индекс по `cn`
2. **I1.2** - Таблица `sessions` имеет внешний ключ на `accounts` с `ON DELETE CASCADE`
3. **I1.3** - Поле `sessions.status` ограничено значениями ENUM
4. **I1.4** - Поле `sessions.connected_at` NOT NULL
5. **I1.5** - Миграции версионированы и воспроизводимы

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I1.1 | Интеграционный | Дублирование CN в accounts |
| I1.2 | Интеграционный | Потеря ссылочной целостности при удалении аккаунта |
| I1.3 | Модульный (схема) | Невалидные значения статуса |
| I1.4 | Модульный (схема) | Создание сессии без времени подключения |
| I1.5 | Интеграционный | Невоспроизводимые миграции |

### Конкретные тесты
```sql
-- Тест I1.1: Попытка вставить дубликат CN должна падать
INSERT INTO accounts (cn) VALUES ('test');
INSERT INTO accounts (cn) VALUES ('test'); -- Ожидаем: DUPLICATE KEY ERROR

-- Тест I1.2: Удаление account каскадно удаляет сессии
INSERT INTO accounts (cn) VALUES ('test');
INSERT INTO sessions (account_id, connected_at) VALUES (1, NOW());
DELETE FROM accounts WHERE id = 1;
SELECT * FROM sessions WHERE account_id = 1; -- Ожидаем: 0 rows

-- Тест I1.3: Невалидный статус отклоняется
INSERT INTO sessions (account_id, connected_at, status) VALUES (1, NOW(), 'invalid'); -- Ожидаем: ERROR

-- Тест I1.4: NULL в connected_at отклоняется
INSERT INTO sessions (account_id, connected_at) VALUES (1, NULL); -- Ожидаем: ERROR
```

### Условия перехода
- [ ] Все миграции применяются без ошибок
- [ ] Все тесты схемы проходят
- [ ] Rollback миграций работает

---

## Этап 2: Модели данных (SQLAlchemy)

### Цель
Создать Python-модели, точно соответствующие схеме БД.

### Инварианты
1. **I2.1** - Модели наследуются от declarative_base()
2. **I2.2** - Имена таблиц и полей совпадают со схемой БД
3. **I2.3** - Типы данных в моделях соответствуют SQL типам
4. **I2.4** - Отношения (relationship) настроены корректно
5. **I2.5** - I1.1-I1.4 сохраняются (модели не ослабляют ограничения БД)

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I2.2 | Модульный | Расхождение имен между моделью и БД |
| I2.3 | Модульный | Несоответствие типов (например, str вместо datetime) |
| I2.4 | Интеграционный | Некорректная загрузка связанных объектов |
| I2.5 | Интеграционный | Создание невалидных объектов через ORM |

### Конкретные тесты
```python
# Тест I2.2: Проверка имени таблицы
def test_account_tablename():
    assert Account.__tablename__ == 'accounts'

# Тест I2.3: Проверка типов полей
def test_session_connected_at_type():
    assert isinstance(Session.connected_at.property.columns[0].type, DateTime)

# Тест I2.4: Проверка relationship
def test_account_sessions_relationship():
    account = session.query(Account).filter_by(cn='test').first()
    assert isinstance(account.sessions, list)
    assert all(isinstance(s, Session) for s in account.sessions)

# Тест I2.5: Попытка создать дубликат через ORM ловит IntegrityError
def test_duplicate_cn_raises_error():
    session.add(Account(cn='test'))
    session.commit()
    session.add(Account(cn='test'))
    with pytest.raises(IntegrityError):
        session.commit()
```

### Условия перехода
- [ ] Модели создают таблицы, идентичные миграциям
- [ ] Все тесты моделей проходят
- [ ] SQLAlchemy не генерирует ALTER TABLE при проверке

---

## Этап 3: GeoIP модуль

### Цель
Создать изолированный модуль для работы с GeoIP с кэшированием.

### Инварианты
1. **I3.1** - Модуль не зависит от остальной системы (только от БД)
2. **I3.2** - При cache hit не делается внешний запрос
3. **I3.3** - При cache miss результат сохраняется в БД
4. **I3.4** - При недоступности внешнего API возвращается None (не падает)
5. **I3.5** - Таймаут внешнего запроса не более 5 секунд

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I3.1 | Модульный (imports) | Циклические зависимости |
| I3.2 | Интеграционный (mock) | Лишние внешние запросы |
| I3.3 | Интеграционный | Утечка кэша (не сохранение) |
| I3.4 | Интеграционный (mock) | Падение системы при недоступности GeoIP |
| I3.5 | Интеграционный | Зависание скриптов |

### Конкретные тесты
```python
# Тест I3.2: Cache hit не делает запрос
def test_cache_hit_no_external_request(db, mocker):
    # Создаем кэш
    db.add(GeoIPCache(ip='1.2.3.4', country='Russia', expires_at=future))
    db.commit()
    
    mock_get = mocker.patch('requests.get')
    result = resolve_geoip('1.2.3.4')
    
    assert result['country'] == 'Russia'
    mock_get.assert_not_called()

# Тест I3.4: API недоступен - возвращаем None
def test_api_unavailable_returns_none(db, mocker):
    mocker.patch('requests.get', side_effect=RequestException())
    result = resolve_geoip('1.2.3.4')
    assert result == {'country': None, 'city': None}
```

### Условия перехода
- [ ] Модуль проходит все тесты изолированно
- [ ] Тесты не требуют запущенного OpenVPN
- [ ] Mock тесты проходят без интернета

---

## Этап 4: Скрипт client-connect

### Цель
Создать скрипт, корректно фиксирующий подключение в БД.

### Инварианты
1. **I4.1** - Скрипт читает только переменные окружения OpenVPN
2. **I4.2** - Скрипт создает или находит account по CN
3. **I4.3** - Скрипт создает запись session со статусом 'active'
4. **I4.4** - Скрипт использует GeoIP модуль (I3.x)
5. **I4.5** - При любой ошибке скрипт возвращает exit 0 (не блокирует VPN)
6. **I4.6** - Скрипт не читает из БД (только INSERT)

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I4.1 | Интеграционный | Зависимость от других источников данных |
| I4.2 | Интеграционный | Создание дубликатов account |
| I4.3 | Интеграционный | Некорректный статус сессии |
| I4.4 | Модульный (mock) | Нарушение границ модулей |
| I4.5 | Интеграционный (fault injection) | Блокировка VPN при ошибках |
| I4.6 | Статический анализ (ast) | Нарушение архитектурной границы |

### Конкретные тесты
```python
# Тест I4.2: Создание нового account
def test_connect_creates_account(db, env):
    env['common_name'] = 'newuser'
    env['trusted_ip'] = '1.2.3.4'
    
    run_client_connect(env)
    
    account = db.query(Account).filter_by(cn='newuser').first()
    assert account is not None

# Тест I4.2: Использование существующего account
def test_connect_uses_existing_account(db, env):
    db.add(Account(cn='existing'))
    db.commit()
    
    env['common_name'] = 'existing'
    env['trusted_ip'] = '1.2.3.4'
    
    run_client_connect(env)
    
    assert db.query(Account).filter_by(cn='existing').count() == 1

# Тест I4.3: Сессия создается со статусом active
def test_connect_creates_active_session(db, env):
    env['common_name'] = 'user'
    env['trusted_ip'] = '1.2.3.4'
    
    run_client_connect(env)
    
    session = db.query(Session).first()
    assert session.status == 'active'
    assert session.disconnected_at is None

# Тест I4.5: При ошибке БД возвращаем 0
def test_connect_db_error_returns_zero(db, env, mocker):
    mocker.patch('MySQLdb.connect', side_effect=Exception('DB down'))
    
    result = run_client_connect(env)
    
    assert result == 0
```

### Условия перехода
- [ ] Скрипт проходит все тесты
- [ ] Скрипт не падает при недоступности БД
- [ ] Тесты I4.5 (fault injection) проходят

---

## Этап 5: Скрипт client-disconnect

### Цель
Создать скрипт, корректно закрывающий сессию.

### Инварианты
1. **I5.1** - Скрипт обновляет только последнюю активную сессию по CN
2. **I5.2** - Скрипт устанавливает `disconnected_at = NOW()`
3. **I5.3** - Скрипт меняет статус на 'closed'
4. **I5.4** - Скрипт сохраняет bytes_sent/bytes_received
5. **I5.5** - При ошибке скрипт возвращает exit 0
6. **I5.6** - Скрипт не создает новых записей (только UPDATE)

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I5.1 | Интеграционный | Обновление не той сессии |
| I5.2 | Интеграционный | Неустановленное время отключения |
| I5.3 | Интеграционный | Некорректный статус после отключения |
| I5.4 | Интеграционный | Потеря статистики трафика |
| I5.5 | Интеграционный (fault injection) | Блокировка отключения |
| I5.6 | Статический анализ (ast) | Нарушение границы (INSERT вместо UPDATE) |

### Конкретные тесты
```python
# Тест I5.1: Обновляется только активная сессия
def test_disconnect_updates_only_active(db, env):
    account = Account(cn='user')
    db.add(account)
    db.flush()
    
    # Старая закрытая сессия
    old_session = Session(account_id=account.id, connected_at=past, disconnected_at=past, status='closed')
    db.add(old_session)
    
    # Новая активная сессия
    new_session = Session(account_id=account.id, connected_at=now, status='active')
    db.add(new_session)
    db.commit()
    
    env['common_name'] = 'user'
    run_client_disconnect(env)
    
    db.refresh(old_session)
    db.refresh(new_session)
    
    assert old_session.status == 'closed'  # Не изменилась
    assert new_session.status == 'closed'  # Обновилась

# Тест I5.2-I5.4: Корректное закрытие сессии
def test_disconnect_closes_session_correctly(db, env):
    account = Account(cn='user')
    db.add(account)
    db.flush()
    db.add(Session(account_id=account.id, connected_at=now, status='active'))
    db.commit()
    
    env['common_name'] = 'user'
    env['bytes_sent'] = '1000'
    env['bytes_received'] = '2000'
    
    run_client_disconnect(env)
    
    session = db.query(Session).first()
    assert session.status == 'closed'
    assert session.disconnected_at is not None
    assert session.bytes_sent == 1000
    assert session.bytes_received == 2000
```

### Условия перехода
- [ ] Скрипт корректно закрывает сессии
- [ ] При отсутствии активной сессии скрипт не падает
- [ ] Тесты I5.5 проходят

---

## Этап 6: Фоновые синхронизации (cert_sync, crl_checker, ccd_checker)

### Цель
Создать периодические задачи для синхронизации метаданных.

### Инварианты
1. **I6.1** - cert_sync обновляет `valid_from`, `valid_to` из сертификатов
2. **I6.2** - crl_checker обновляет `is_revoked`, `revoked_at` из CRL
3. **I6.3** - ccd_checker обновляет `has_ccd`, `ccd_updated_at`
4. **I6.4** - Все скрипты идемпотентны (повторный запуск не ломает данные)
5. **I6.5** - Скрипты не создают новых accounts (только UPDATE)

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I6.1 | Интеграционный (mock filesystem) | Некорректное чтение дат сертификатов |
| I6.2 | Интеграционный (mock CRL) | Некорректная проверка отзыва |
| I6.3 | Интеграционный (mock filesystem) | Некорректная проверка CCD |
| I6.4 | Интеграционный | Повреждение данных при повторном запуске |
| I6.5 | Статический анализ | Создание accounts вне скрипта connect |

### Конкретные тесты
```python
# Тест I6.1: Обновление сроков сертификата
def test_cert_sync_updates_dates(db, tmp_path, mocker):
    # Создаем мок сертификата
    cert_file = tmp_path / 'client.crt'
    cert_file.write_text('...')  # PEM content
    
    db.add(Account(cn='test'))
    db.commit()
    
    mocker.patch('collector.config.CERTS_DIR', tmp_path)
    run_cert_sync()
    
    account = db.query(Account).filter_by(cn='test').first()
    assert account.valid_from is not None
    assert account.valid_to is not None

# Тест I6.4: Идемпотентность
def test_cert_sync_idempotent(db, tmp_path, mocker):
    db.add(Account(cn='test', valid_from=datetime(2024, 1, 1), valid_to=datetime(2025, 1, 1)))
    db.commit()
    
    mocker.patch('collector.config.CERTS_DIR', tmp_path)
    
    run_cert_sync()
    run_cert_sync()  # Второй раз
    
    # Данные не должны сломаться
    account = db.query(Account).filter_by(cn='test').first()
    assert account.valid_from == datetime(2024, 1, 1)
```

### Условия перехода
- [ ] Все три скрипта проходят тесты
- [ ] Скрипты можно запускать многократно без вреда
- [ ] При отсутствии файлов скрипты не падают

---

## Этап 7: REST API (endpoints)

### Цель
Реализовать API endpoints согласно спецификации.

### Инварианты
1. **I7.1** - API только читает из БД (нет INSERT/UPDATE/DELETE)
2. **I7.2** - Ответы соответствуют формату из api-design.md
3. **I7.3** - Пагинация работает корректно
4. **I7.4** - Фильтры работают как указано в спецификации
5. **I7.5** - При отсутствии данных возвращается 404 или пустой список
6. **I7.6** - Аутентификация обязательна для всех endpoints

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I7.1 | Статический анализ (ast) | Нарушение архитектурной границы |
| I7.2 | Контрактное тестирование (schemathesis) | Изменение формата ответа |
| I7.3 | Модульный | Некорректная пагинация |
| I7.4 | Модульный | Неработающие фильтры |
| I7.5 | Модульный | 500 ошибка вместо 404 |
| I7.6 | Модульный | Незащищенные endpoints |

### Конкретные тесты
```python
# Тест I7.2: Формат ответа /accounts/{cn}
def test_get_account_format(client, db):
    db.add(Account(cn='test', valid_from=datetime(2024, 1, 1), valid_to=datetime(2025, 1, 1)))
    db.commit()
    
    response = client.get('/api/v1/accounts/test', auth=('admin', 'pass'))
    
    assert response.status_code == 200
    data = response.json()
    assert 'cn' in data
    assert 'valid_from' in data
    assert 'valid_to' in data
    assert 'is_revoked' in data
    assert 'has_ccd' in data
    assert 'can_connect' in data
    assert 'last_session' in data

# Тест I7.3: Пагинация
def test_accounts_pagination(client, db):
    for i in range(25):
        db.add(Account(cn=f'user{i}'))
    db.commit()
    
    response = client.get('/api/v1/accounts?page=1&per_page=10', auth=('admin', 'pass'))
    data = response.json()
    
    assert len(data['data']) == 10
    assert data['meta']['total'] == 25
    assert data['meta']['total_pages'] == 3

# Тест I7.6: Без аутентификации - 401
def test_unauthorized_returns_401(client):
    response = client.get('/api/v1/accounts')
    assert response.status_code == 401
```

### Условия перехода
- [ ] Все endpoints покрыты тестами
- [ ] Контрактные тесты проходят
- [ ] Swagger UI отображает корректную схему

---

## Этап 8: Web UI

### Цель
Реализовать веб-интерфейс на основе API.

### Инварианты
1. **I8.1** - UI использует только REST API (прямых запросов к БД нет)
2. **I8.2** - Все страницы требуют аутентификации
3. **I8.3** - Отображаемые данные соответствуют API ответам
4. **I8.4** - Навигация работает корректно

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I8.1 | Интеграционный (e2e) | Прямые SQL запросы из UI |
| I8.2 | E2E (Playwright/Selenium) | Незащищенные страницы |
| I8.3 | E2E | Расхождение данных UI и API |
| I8.4 | E2E | Сломанные ссылки |

### Конкретные тесты
```python
# Тест I8.2: Редирект на логин
def test_unauthorized_redirects_to_login(page):
    page.goto('http://localhost:8000/')
    assert '/login' in page.url

# Тест I8.3: Данные на dashboard соответствуют API
def test_dashboard_shows_correct_data(page, db):
    db.add(Account(cn='test'))
    db.commit()
    
    page.goto('http://localhost:8000/')
    page.fill('input[name="username"]', 'admin')
    page.fill('input[name="password"]', 'pass')
    page.click('button[type="submit"]')
    
    assert page.inner_text('text=test') == 'test'
```

### Условия перехода
- [ ] Все страницы отображаются корректно
- [ ] E2E тесты проходят
- [ ] Ручное тестирование пройдено

---

## Этап 9: Docker окружение

### Цель
Создать полное Docker окружение для разработки и тестирования.

### Иварианты
1. **I9.1** - `docker-compose up` поднимает все сервисы
2. **I9.2** - OpenVPN сервер генерирует PKI при первом запуске
3. **I9.3** - Клиент может подключиться к серверу
4. **I9.4** - При подключении создается запись в БД
5. **I9.5** - При отключении сессия закрывается

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I9.1 | Интеграционный | Нерабочий compose |
| I9.2 | Интеграционный | Отсутствие сертификатов |
| I9.3 | Интеграционный | Нерабочий VPN |
| I9.4 | E2E | Не работает интеграция скриптов |
| I9.5 | E2E | Не работает disconnect скрипт |

### Конкретные тесты
```bash
# Тест I9.1-I9.3: Поднимаем окружение
docker-compose up -d
sleep 10
# Проверяем healthcheck всех сервисов

# Тест I9.4-I9.5: Подключаем клиента и проверяем БД
docker-compose exec openvpn-client openvpn --config /etc/openvpn/client.conf &
sleep 5
# Проверяем что сессия создалась
docker-compose exec mysql mysql -e "SELECT * FROM sessions WHERE status='active'"
# Отключаем клиента
kill %1
sleep 2
# Проверяем что сессия закрылась
docker-compose exec mysql mysql -e "SELECT * FROM sessions WHERE status='closed'"
```

### Условия перехода
- [ ] Все сервисы стартуют
- [ ] VPN подключение работает
- [ ] Данные фиксируются в БД

---

## Этап 10: Интеграционное тестирование

### Цель
Проверить всю систему в комплексе.

### Инварианты
1. **I10.1** - Полный цикл: подключение → данные в БД → отображение в UI
2. **I10.2** - Множественные подключения/отключения работают корректно
3. **I10.3** - Синхронизации обновляют метаданные
4. **I10.4** - Система устойчива к перезапуску

### Тесты

| Инвариант | Тип теста | Что предотвращает |
|-----------|-----------|-------------------|
| I10.1 | E2E | Разрыв цепочки данных |
| I10.2 | Нагрузочный | Race conditions |
| I10.3 | Интеграционный | Устаревшие метаданные |
| I10.4 | Интеграционный | Потеря данных при рестарте |

### Условия перехода
- [ ] Все интеграционные тесты проходят
- [ ] Ручное тестирование пройдено
- [ ] Документация обновлена

---

## Архитектурные конфликты (на данный момент не выявлены)

На момент составления плана архитектурных конфликтов между этапами не выявлено. Каждый следующий этап:
- Опирается на проверяемые результаты предыдущего
- Не требует пересмотра инвариантов предыдущих этапов
- Добавляет новые инварианты без нарушения старых
