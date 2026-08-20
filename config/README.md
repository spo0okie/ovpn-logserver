# Конфигурация OpenVPN LogServer

Централизованная конфигурация для всех компонентов системы OpenVPN LogServer.
Все настройки хранятся в YML файлах в папке `config/`.

## Структура

```
config/
├── database.yaml    # Конфигурация базы данных
├── auth.yaml        # Учетные данные (пароли в открытом виде)
├── openvpn.yaml     # Конфигурация путей OpenVPN
└── web.yaml         # Конфигурация web-приложения
```

## Файлы конфигурации

### database.yaml

Централизованный файл конфигурации базы данных для всех компонентов системы.

```yaml
# Конфигурация базы данных OpenVPN LogServer
database:
  # Параметры подключения к MySQL
  host: localhost
  port: 3306
  name: openvpn_logs
  user: openvpn_user
  password: СМЕНИТЕ_ПАРОЛЬ_БД      # Пароль в открытом виде

  # Параметры пула соединений
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600

  # Дополнительные параметры подключения
  charset: utf8mb4
```

#### Параметры database.yaml

| Параметр | Тип | Описание | Значение по умолчанию |
|----------|-----|----------|----------------------|
| `host` | string | Хост MySQL сервера | `localhost` |
| `port` | int | Порт MySQL | `3306` |
| `name` | string | Имя базы данных | `openvpn_logs` |
| `user` | string | Пользователь БД | `openvpn_user` |
| `password` | string | Пароль БД (в открытом виде) | - |
| `pool_size` | int | Размер пула соединений | `10` |
| `max_overflow` | int | Максимальное превышение пула | `20` |
| `pool_timeout` | int | Таймаут получения соединения (сек) | `30` |
| `pool_recycle` | int | Время пересоздания соединения (сек) | `3600` |
| `charset` | string | Кодировка соединения | `utf8mb4` |

### auth.yaml

Конфигурация аутентификации для Web UI и API.

```yaml
# Конфигурация аутентификации OpenVPN LogServer
auth:
  web:
    username: admin
    password: СМЕНИТЕ_ПАРОЛЬ        # Пароль в открытом виде (legacy; лучше password_hash)
```

#### Параметры auth.yaml

| Параметр | Тип | Описание | Значение по умолчанию |
|----------|-----|----------|----------------------|
| `web.username` | string | Имя пользователя для Basic Auth | `admin` |
| `web.password` | string | Пароль в открытом виде | - |

### openvpn.yaml

Конфигурация путей к файлам и директориям OpenVPN для collector модулей.

```yaml
# Конфигурация OpenVPN для collector модулей
openvpn:
  # Базовая директория OpenVPN
  base_dir: /etc/openvpn

  # Директория с сертификатами клиентов
  certs_dir: /etc/openvpn/certs

  # Расширение файлов сертификатов
  cert_extension: .crt

  # Путь к CRL файлу (Certificate Revocation List)
  crl_file: /etc/openvpn/crl.pem

  # Директория с CCD (Client Config Directory) файлами
  ccd_dir: /etc/openvpn/ccd
```

#### Параметры openvpn.yaml

| Параметр | Тип | Описание | Значение по умолчанию |
|----------|-----|----------|----------------------|
| `base_dir` | string | Базовая директория OpenVPN | `/etc/openvpn` |
| `certs_dir` | string | Директория с сертификатами клиентов | `/etc/openvpn/certs` |
| `cert_extension` | string | Расширение файлов сертификатов | `.crt` |
| `crl_file` | string | Путь к CRL файлу | `/etc/openvpn/crl.pem` |
| `ccd_dir` | string | Директория с CCD файлами | `/etc/openvpn/ccd` |

#### Приоритет настроек

Приоритет (от высшего к низшему):
1. **Переменные окружения** — для Docker и временного переопределения
2. **config/openvpn.yaml** — основная конфигурация
3. **Значения по умолчанию**

Переменные окружения:
- `OPENVPN_DIR` — базовая директория
- `CERTS_DIR` — директория с сертификатами
- `CERT_EXTENSION` — расширение файлов сертификатов
- `CRL_FILE` — путь к CRL файлу
- `CCD_DIR` — директория с CCD файлами

### web.yaml

Конфигурация web-приложения. **Важно:** учетные данные (пароли) хранятся в отдельном файле [`config/auth.yaml`](auth.yaml).

```yaml
# Конфигурация Web приложения OpenVPN LogServer

# Настройки приложения
app:
  # Хост для прослушивания (127.0.0.1 для локального доступа, 0.0.0.0 для всех интерфейсов)
  host: 127.0.0.1

  # Порт
  port: 8000

  # Количество worker-процессов
  workers: 2

  # Секретный ключ для сессий (измените на случайную строку!)
  secret_key: "change-this-to-random-secret-key-min-32-chars"

  # Режим отладки (не включайте в production!)
  debug: false

# Настройки логирования
logging:
  # Уровень логирования: DEBUG, INFO, WARNING, ERROR
  level: INFO

  # Путь к файлу логов
  file: /opt/openvpn-logserver/logs/web.log

  # Максимальный размер файла лога в байтах
  max_bytes: 10485760  # 10 MB

  # Количество резервных копий логов
  backup_count: 5

# Настройки пагинации
pagination:
  # Количество элементов на странице по умолчанию
  default_page_size: 25

  # Максимальное количество элементов на странице
  max_page_size: 100

# Настройки CORS (для API доступа из других доменов)
cors:
  # Разрешенные источники (список или ["*"] для всех)
  allow_origins: ["*"]

  # Разрешенные методы
  allow_methods: ["GET", "POST"]

  # Разрешенные заголовки
  allow_headers: ["*"]
```

## Примеры конфигурации

### Минимальная конфигурация (production)

**config/database.yaml:**
```yaml
database:
  host: localhost
  port: 3306
  name: openvpn_logs
  user: openvpn_user
  password: your_secure_password_here
  pool_size: 10
  max_overflow: 20
```

**config/auth.yaml:**
```yaml
auth:
  web:
    username: admin
    password: your_admin_password_here
```

**config/web.yaml:**
```yaml
app:
  host: 127.0.0.1
  port: 8000
  workers: 2
  secret_key: "your-very-secret-key-here-min-32-chars"

logging:
  level: INFO
  file: /opt/openvpn-logserver/logs/web.log
```

### Конфигурация для Docker

**config/database.yaml:**
```yaml
database:
  host: mysql  # Имя сервиса в docker-compose
  port: 3306
  name: openvpn_logs
  user: openvpn
  password: docker_password_here
  pool_size: 10
  max_overflow: 20
```

**config/auth.yaml:**
```yaml
auth:
  web:
    username: admin
    password: docker_admin_password
```

**config/web.yaml:**
```yaml
app:
  host: 0.0.0.0  # Слушаем на всех интерфейсах
  port: 8000
  workers: 2
  secret_key: "docker-secret-key-change-in-production"

logging:
  level: INFO
  file: /opt/openvpn-logserver/logs/web.log
```

### Конфигурация с удаленной БД

**config/database.yaml:**
```yaml
database:
  host: db.example.com
  port: 3306
  name: openvpn_logs
  user: openvpn_user
  password: remote_password_here
  pool_size: 20
  max_overflow: 30
  pool_timeout: 60
  pool_recycle: 1800
  charset: utf8mb4
```

## Права доступа

Рекомендуемые права доступа к файлам конфигурации:

```bash
# Владелец - пользователь приложения
sudo chown -R ovpn-logserver:ovpn-logserver /opt/openvpn-logserver/config

# Только владелец может читать (содержит пароли в открытом виде)
sudo chmod 640 /opt/openvpn-logserver/config/*.yaml

# Директория недоступна для других
sudo chmod 750 /opt/openvpn-logserver/config
```

## Использование в коде

### Python API

```python
from core.config import load_db_config, get_database_url, get_web_auth_credentials

# Загрузить конфигурацию БД
config = load_db_config()
print(config['host'])  # localhost
print(config['port'])  # 3306

# Получить URL для SQLAlchemy
url = get_database_url()
# mysql+pymysql://openvpn_user:password@localhost:3306/openvpn_logs

# Получить учетные данные для аутентификации
auth = get_web_auth_credentials()
print(auth['username'])  # admin
print(auth['password'])  # значение из config/auth.yaml
```

### Кэширование

Конфигурация кэшируется для повторного использования. Для принудительной перезагрузки:

```python
from core.config import reload_config

# Перезагрузить конфигурацию
config = reload_config()
```

## Проверка конфигурации

```bash
# Проверить что файл существует и валиден
python3 -c "
from core.config import load_db_config, get_database_url, get_database_url_safe
config = load_db_config()
print('Config loaded successfully:')
print(f'  Host: {config[\"host\"]}')
print(f'  Port: {config[\"port\"]}')
print(f'  Database: {config[\"name\"]}')
print(f'  User: {config[\"user\"]}')
print(f'  URL: {get_database_url_safe()}')
"
```

## Решение проблем

### Ошибка: "Configuration file not found"

**Причина:** Файл `config/database.yaml` не найден.

**Решение:**
```bash
# Проверить наличие файла
ls -la config/database.yaml

# Создать если отсутствует
cp config/database.yaml.example config/database.yaml
```

### Ошибка: "Invalid configuration: 'database' section not found"

**Причина:** В YAML файле отсутствует секция `database`.

**Решение:** Проверить структуру файла:
```yaml
database:
  host: localhost
  # ... остальные параметры
```

## Ссылки

- [Развёртывание и systemd](../docs/deployment.md)
- [Архитектура и конфигурация](../docs/architecture.md)
- [Документация по миграциям](../database/README.md)
