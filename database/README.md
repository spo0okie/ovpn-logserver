# Database Module

Модуль для управления базой данных OpenVPN Log Server.

## Структура

```
database/
├── alembic.ini              # Конфигурация Alembic
├── migrations/              # Директория с миграциями
│   ├── env.py              # Окружение Alembic (использует централизованный конфиг)
│   ├── script.py.mako      # Шаблон для новых миграций
│   └── versions/           # Директория с версиями миграций
│       └── 001_initial_schema.py  # Начальная миграция
├── tests/                   # Тесты для схемы БД
│   └── test_schema.py      # Тесты инвариантов
└── requirements.txt        # Зависимости
```

## Конфигурация

Модуль использует **централизованную конфигурацию** из файла `config/database.yaml`.

### Порядок приоритета конфигурации:

1. Переменная окружения `DATABASE_URL` (для Alembic и обратной совместимости)
2. Файл `config/database.yaml` (рекомендуемый способ)
3. Значения по умолчанию

### Файл config/database.yaml

```yaml
# Конфигурация базы данных OpenVPN LogServer
database:
  # Параметры подключения к MySQL
  host: localhost
  port: 3306
  name: openvpn_logs
  user: openvpn_user
  password: ${DB_PASSWORD}  # Берется из переменной окружения DB_PASSWORD

  # Параметры пула соединений
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600

  # Дополнительные параметры подключения
  charset: utf8mb4
```

## Переменные окружения

### Обязательная переменная

| Переменная | Описание | Пример |
|------------|----------|--------|
| `DB_PASSWORD` | Пароль для подключения к БД | `your_secure_password` |

### Опциональные переменные

| Переменная | Описание | Значение по умолчанию |
|------------|----------|----------------------|
| `DATABASE_URL` | URL для Alembic (может использоваться вместо config) | формируется из конфига |
| `DB_HOST` | Хост БД | `localhost` |
| `DB_PORT` | Порт БД | `3306` |
| `DB_NAME` | Имя базы данных | `openvpn_logs` |
| `DB_USER` | Пользователь БД | `openvpn_user` |

## Использование

### Подготовка

```bash
# Установить зависимости
pip install -r database/requirements.txt

# Установить пароль БД в переменную окружения
export DB_PASSWORD="your_secure_password"
```

### Применение миграций

**Способ 1: Через централизованный конфиг (рекомендуется)**

```bash
# Убедитесь что создан config/database.yaml и установлена переменная DB_PASSWORD
export DB_PASSWORD="your_secure_password"

cd database
alembic upgrade head
```

**Способ 2: Через переменную окружения DATABASE_URL**

```bash
export DATABASE_URL="mysql+pymysql://openvpn_user:your_secure_password@localhost:3306/openvpn_logs"

cd database
alembic upgrade head
```

### Откат миграций

```bash
cd database

# Откат на одну версию назад
alembic downgrade -1

# Откат к начальному состоянию
alembic downgrade base
```

### Создание новой миграции

```bash
cd database

# Создать новую миграцию с автогенерацией (требуются модели SQLAlchemy)
# alembic revision --autogenerate -m "описание миграции"

# Создать пустую миграцию
alembic revision -m "описание миграции"
```

### Просмотр истории миграций

```bash
cd database

# Текущая версия
alembic current

# История
alembic history --verbose
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

| Поле | Тип | Описание |
|------|-----|----------|
| id | INT UNSIGNED | Первичный ключ |
| cn | VARCHAR(255) | Common Name сертификата (уникальный) |
| valid_from | DATETIME | Дата начала действия сертификата |
| valid_to | DATETIME | Дата окончания действия сертификата |
| is_revoked | BOOLEAN | Отозван ли сертификат |
| revoked_at | DATETIME | Дата отзыва |
| has_ccd | BOOLEAN | Есть ли CCD конфигурация |
| ccd_updated_at | DATETIME | Дата обновления CCD |
| created_at | DATETIME | Дата создания записи |
| updated_at | DATETIME | Дата обновления записи |

### sessions
Журнал VPN сессий.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BIGINT UNSIGNED | Первичный ключ |
| account_id | INT UNSIGNED | Внешний ключ на accounts |
| connected_at | DATETIME | Время подключения |
| disconnected_at | DATETIME | Время отключения |
| source_ip | VARCHAR(45) | IP адрес клиента |
| country | VARCHAR(100) | Страна (GeoIP) |
| city | VARCHAR(100) | Город (GeoIP) |
| bytes_sent | BIGINT UNSIGNED | Отправлено байт |
| bytes_received | BIGINT UNSIGNED | Получено байт |
| virtual_ip | VARCHAR(45) | Внутренний IP в VPN |
| status | ENUM | Статус: active, closed |

### connection_attempts
Неудачные попытки подключения.

| Поле | Тип | Описание |
|------|-----|----------|
| id | BIGINT UNSIGNED | Первичный ключ |
| account_id | INT UNSIGNED | Внешний ключ на accounts (может быть NULL) |
| attempted_at | DATETIME | Время попытки |
| source_ip | VARCHAR(45) | IP адрес |
| cert_cn | VARCHAR(255) | CN из сертификата |
| failure_reason | VARCHAR(255) | Причина отказа |
| failure_type | ENUM | Тип ошибки |

### geoip_cache
Кэш GeoIP данных.

| Поле | Тип | Описание |
|------|-----|----------|
| ip | VARCHAR(45) | Первичный ключ (IP адрес) |
| country | VARCHAR(100) | Страна |
| country_code | VARCHAR(2) | Код страны |
| city | VARCHAR(100) | Город |
| cached_at | DATETIME | Время кэширования |
| expires_at | DATETIME | Время истечения |

## Тестирование

### Запуск тестов

```bash
# Установка зависимостей
pip install -r database/requirements.txt

# Запуск тестов схемы
pytest database/tests/test_schema.py -v

# Запуск всех тестов модуля
pytest database/tests/ -v
```

### Переменные окружения для тестов

| Переменная | Описание | Значение по умолчанию |
|------------|----------|----------------------|
| `TEST_DB_HOST` | Хост тестовой БД | `localhost` |
| `TEST_DB_PORT` | Порт тестовой БД | `3306` |
| `TEST_DB_USER` | Пользователь тестовой БД | `openvpn_user` |
| `TEST_DB_PASSWORD` | Пароль тестовой БД | `openvpn_password` |
| `TEST_DB_NAME` | Имя тестовой БД | `openvpn_logs_test` |

## Решение проблем

### Ошибка: "Configuration file not found: config/database.yaml"

**Причина:** Отсутствует файл конфигурации БД.

**Решение:**
```bash
# Создать файл конфигурации
mkdir -p config
cat > config/database.yaml <<EOF
database:
  host: localhost
  port: 3306
  name: openvpn_logs
  user: openvpn_user
  password: \${DB_PASSWORD}
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600
  charset: utf8mb4
EOF
```

### Ошибка: "DB_PASSWORD environment variable is not set"

**Причина:** Не установлена переменная окружения с паролем.

**Решение:**
```bash
export DB_PASSWORD="your_secure_password"
```

### Ошибка подключения к MySQL

**Проверка:**
```bash
# Проверить доступность MySQL
mysql -u openvpn_user -p -e "SELECT 1;"

# Проверить права пользователя
mysql -u root -p -e "SHOW GRANTS FOR 'openvpn_user'@'localhost';"
```

## Интеграция с core.config

Модуль миграций использует [`core.config.get_database_url()`](core/config.py:120) для получения URL подключения к БД:

```python
# database/migrations/env.py
from core.config import get_database_url

# Получаем URL базы данных из централизованной конфигурации
DB_URL = get_database_url()
```

Это обеспечивает единый источник конфигурации для всех компонентов системы.
