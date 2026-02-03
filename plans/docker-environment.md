# Docker окружение для разработки

## Архитектура контейнеров

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Docker Compose Network                              │
│                                                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐           │
│  │   openvpn-server │  │   web            │  │  openvpn-client  │           │
│  │   (VPN сервер)   │  │   (Приложение)   │  │  (VPN клиент)    │           │
│  │                  │  │                  │  │                  │           │
│  │  - OpenVPN 2.5+  │  │  - FastAPI Web   │  │  - OpenVPN       │           │
│  │  - PKI/Certs     │  │  - Collector     │  │  - Client certs  │           │
│  │  - CCD configs   │  │  - Scripts       │  │  - Test client   │           │
│  │                  │  │                  │  │                  │           │
│  │  Ports:          │  │  Ports:          │  │                  │           │
│  │  - 1194/udp      │  │  - 8000/tcp      │  │                  │           │
│  │  - 7505/tcp      │  │                  │  │                  │           │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘           │
│           │                     │                     │                       │
│           └─────────────────────┼─────────────────────┘                       │
│                                 │                                             │
│                                 ▼                                             │
│                    ┌──────────────────────┐                                  │
│                    │      mysql           │                                  │
│                    │   (MySQL 8.0)        │                                  │
│                    │                      │                                  │
│                    │  - openvpn_logs DB   │                                  │
│                    │  - Инициализация     │                                  │
│                    └──────────────────────┘                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Структура директорий

```
docker/
├── docker-compose.yml           # Основной compose файл
├── .env                         # Переменные окружения
│
├── openvpn-server/              # OpenVPN сервер
│   ├── Dockerfile
│   ├── server.conf
│   ├── entrypoint.sh
│   └── scripts/
│       ├── client-connect
│       └── client-disconnect
│
├── openvpn-client/              # OpenVPN клиент (для тестов)
│   ├── Dockerfile
│   ├── client.conf
│   └── entrypoint.sh
│
├── web/                         # Web приложение
│   ├── Dockerfile
│   └── requirements.txt
│
├── mysql/                       # База данных
│   └── init.sql                 # Инициализация схемы
│
└── shared/                      # Общие данные (volumes)
    ├── pki/                     # PKI (генерируется)
    ├── ccd/                     # Client configs
    └── logs/                    # Логи
```

## Переменные окружения

### Обязательные переменные

| Переменная | Описание | Пример |
|------------|----------|--------|
| `DB_PASSWORD` | Пароль для подключения к БД | `collectorpass` |

### Опциональные переменные

| Переменная | Описание | Значение по умолчанию |
|------------|----------|----------------------|
| `MYSQL_ROOT_PASSWORD` | Пароль root MySQL | `root_password` |
| `MYSQL_DATABASE` | Имя базы данных | `openvpn_logs` |
| `MYSQL_USER` | Пользователь MySQL | `openvpn` |
| `MYSQL_PASSWORD` | Пароль пользователя MySQL | `openvpn_password` |
| `DATABASE_URL` | URL подключения к БД (для Alembic) | формируется автоматически |
| `SECRET_KEY` | Секретный ключ для web | `your-secret-key-change-in-production` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Время жизни токена | `30` |

### Файл .env

```bash
# Database
MYSQL_ROOT_PASSWORD=root_password
MYSQL_DATABASE=openvpn_logs
MYSQL_USER=openvpn
MYSQL_PASSWORD=openvpn_password

# App
SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Для совместимости с централизованной конфигурацией
DB_PASSWORD=openvpn_password
```

## Docker Compose

### docker-compose.yml

```yaml
# =============================================================================
# Docker Compose конфигурация для OpenVPN LogServer.
# =============================================================================
# Сервисы:
# - mysql: База данных MySQL 8.0
# - openvpn-server: Сервер OpenVPN с генерацией PKI
# - openvpn-client: Клиент OpenVPN для тестирования
# - web: FastAPI приложение
#
# Инварианты:
# - I9.1: docker-compose up поднимает все сервисы
# - I9.2: OpenVPN сервер генерирует PKI при первом запуске
# - I9.3: Клиент может подключиться к серверу
# - I9.4: При подключении создается запись в БД
# - I9.5: При отключении сессия закрывается
# =============================================================================

version: '3.8'

services:
  # MySQL база данных
  mysql:
    image: mysql:8.0
    container_name: openvpn-mysql
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-root_password}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-openvpn_logs}
      MYSQL_USER: ${MYSQL_USER:-openvpn}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-openvpn_password}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - openvpn-network
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p${MYSQL_ROOT_PASSWORD:-root_password}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  # OpenVPN сервер
  openvpn-server:
    build:
      context: ../
      dockerfile: docker/openvpn-server/Dockerfile
    container_name: openvpn-server
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.ip_forward=1
    ports:
      - "1194:1194/udp"
    volumes:
      - openvpn_pki:/etc/openvpn/pki
      - openvpn_ccd:/etc/openvpn/ccd
      - openvpn_certs:/etc/openvpn/certs
      - ../config:/opt/openvpn-logserver/config:ro  # Монтируем конфигурацию
    networks:
      - openvpn-network
    environment:
      - DB_PASSWORD=${MYSQL_PASSWORD:-openvpn_password}
      - DATABASE_URL=mysql+pymysql://${MYSQL_USER:-openvpn}:${MYSQL_PASSWORD:-openvpn_password}@mysql:3306/${MYSQL_DATABASE:-openvpn_logs}
      - OPENVPN_DIR=/etc/openvpn
      - CERTS_DIR=/etc/openvpn/certs
      - CRL_FILE=/etc/openvpn/pki/crl.pem
      - CCD_DIR=/etc/openvpn/ccd
    depends_on:
      mysql:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "pgrep", "openvpn"]
      interval: 10s
      timeout: 5s
      retries: 3

  # OpenVPN клиент (для тестирования)
  openvpn-client:
    build:
      context: ../
      dockerfile: docker/openvpn-client/Dockerfile
    container_name: openvpn-client
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.ip_forward=1
    networks:
      - openvpn-network
    environment:
      - OPENVPN_SERVER=openvpn-server
      - OPENVPN_PORT=1194
    depends_on:
      - openvpn-server
    profiles:
      - client
    command: ["sleep", "infinity"]

  # Web приложение (FastAPI)
  web:
    build:
      context: ../
      dockerfile: docker/web/Dockerfile
    container_name: openvpn-web
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DB_PASSWORD=${MYSQL_PASSWORD:-openvpn_password}
      - DATABASE_URL=mysql+pymysql://${MYSQL_USER:-openvpn}:${MYSQL_PASSWORD:-openvpn_password}@mysql:3306/${MYSQL_DATABASE:-openvpn_logs}
      - SECRET_KEY=${SECRET_KEY:-your-secret-key-change-in-production}
      - ACCESS_TOKEN_EXPIRE_MINUTES=${ACCESS_TOKEN_EXPIRE_MINUTES:-30}
    volumes:
      - ../config:/opt/openvpn-logserver/config:ro  # Монтируем конфигурацию
      - ../logs:/opt/openvpn-logserver/logs  # Логи
    networks:
      - openvpn-network
    depends_on:
      mysql:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s

volumes:
  mysql_data:
    driver: local
  openvpn_pki:
    driver: local
  openvpn_ccd:
    driver: local
  openvpn_certs:
    driver: local

networks:
  openvpn-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

## Конфигурация в Docker

### Структура конфигурации

В Docker-окружении используется централизованная конфигурация из файлов:

```
config/
├── database.yaml    # Конфигурация БД (монтируется в контейнеры)
└── web.yaml         # Конфигурация web-приложения
```

### Пример config/database.yaml для Docker

```yaml
# Конфигурация базы данных для Docker окружения
database:
  host: mysql
  port: 3306
  name: openvpn_logs
  user: openvpn
  password: ${DB_PASSWORD}  # Берется из переменной окружения

  # Параметры пула соединений
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600

  charset: utf8mb4
```

### Пример config/web.yaml для Docker

```yaml
# Конфигурация Web приложения для Docker окружения
database:
  pool_size: 10
  max_overflow: 20

app:
  host: 0.0.0.0
  port: 8000
  workers: 2
  secret_key: "docker-secret-key-change-in-production"
  debug: false

auth:
  username: admin
  password_hash: "$2b$12$your_bcrypt_hash_here_change_this"
  session_timeout: 480

logging:
  level: INFO
  file: /opt/openvpn-logserver/logs/web.log
  max_bytes: 10485760
  backup_count: 5

pagination:
  default_page_size: 25
  max_page_size: 100
```

## Dockerfile для приложения

### docker/web/Dockerfile

```dockerfile
FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    netcat-traditional \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /opt/openvpn-logserver

# Копируем requirements
COPY web/requirements.txt ./web/
COPY database/requirements.txt ./database/
COPY core/requirements.txt ./core/ 2>/dev/null || true

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r web/requirements.txt
RUN pip install --no-cache-dir -r database/requirements.txt

# Копируем код приложения
COPY web/ ./web/
COPY core/ ./core/
COPY database/ ./database/
COPY collector/ ./collector/
COPY config/ ./config/

# Создаем директорию для логов
RUN mkdir -p logs

# Открываем порт
EXPOSE 8000

# Запускаем приложение
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Dockerfile для OpenVPN сервера

### docker/openvpn-server/Dockerfile

```dockerfile
FROM debian:bookworm-slim

# Установка OpenVPN и зависимостей
RUN apt-get update && apt-get install -y \
    openvpn \
    easy-rsa \
    iptables \
    python3 \
    python3-pip \
    python3-mysqldb \
    python3-yaml \
    net-tools \
    iputils-ping \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python библиотеки для скриптов
RUN pip3 install requests sqlalchemy pymysql --break-system-packages

# Создаем директории
RUN mkdir -p /etc/openvpn/pki /etc/openvpn/ccd /etc/openvpn/scripts /var/log/openvpn

# Копируем конфигурацию
COPY docker/openvpn-server/server.conf /etc/openvpn/server.conf
COPY docker/openvpn-server/entrypoint.sh /entrypoint.sh
COPY docker/openvpn-server/scripts/ /etc/openvpn/scripts/

# Копируем core модули для скриптов
COPY core/ /opt/openvpn-logserver/core/
COPY collector/ /opt/openvpn-logserver/collector/
COPY config/ /opt/openvpn-logserver/config/

RUN chmod +x /entrypoint.sh /etc/openvpn/scripts/*

# PKI будет создан в entrypoint
VOLUME ["/etc/openvpn/pki", "/etc/openvpn/ccd", "/var/log/openvpn"]

EXPOSE 1194/udp

ENTRYPOINT ["/entrypoint.sh"]
```

### docker/openvpn-server/server.conf

```conf
# Основные настройки
port 1194
proto udp
dev tun

# PKI
ca /etc/openvpn/pki/ca.crt
cert /etc/openvpn/pki/issued/server.crt
key /etc/openvpn/pki/private/server.key
dh /etc/openvpn/pki/dh.pem
crl-verify /etc/openvpn/pki/crl.pem

# Сеть
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist /var/log/openvpn/ipp.txt

# Маршрутизация
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"

# CCD
client-config-dir /etc/openvpn/ccd

# Скрипты
client-connect /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# Логирование
log-append /var/log/openvpn/server.log
verb 3
status /var/log/openvpn/status.log

# Безопасность
user nobody
group nogroup
persist-key
persist-tun

# Management interface (для отладки)
management 0.0.0.0 7505

# Проверка активности
keepalive 10 120
cipher AES-256-GCM
auth SHA256
```

### docker/openvpn-server/entrypoint.sh

```bash
#!/bin/bash
set -e

# Включаем форвардинг
echo 1 > /proc/sys/net/ipv4/ip_forward

# Настраиваем iptables
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE || true

# Проверяем/создаем PKI
if [ ! -f /etc/openvpn/pki/ca.crt ]; then
    echo "Initializing PKI..."
    
    # Копируем easy-rsa
    make-cadir /tmp/easy-rsa
    cd /tmp/easy-rsa
    
    # Настройки PKI
    cat > vars << EOF
set_var EASYRSA_REQ_COUNTRY "RU"
set_var EASYRSA_REQ_PROVINCE "Moscow"
set_var EASYRSA_REQ_CITY "Moscow"
set_var EASYRSA_REQ_ORG "OpenVPN LogServer"
set_var EASYRSA_REQ_EMAIL "admin@example.com"
set_var EASYRSA_REQ_OU "IT"
set_var EASYRSA_KEY_SIZE 2048
set_var EASYRSA_CA_EXPIRE 3650
set_var EASYRSA_CERT_EXPIRE 3650
EOF
    
    # Инициализация PKI
    ./easyrsa init-pki
    
    # Создаем CA
    echo "yes" | ./easyrsa build-ca nopass
    
    # Создаем серверный сертификат
    ./easyrsa build-server-full server nopass
    
    # Создаем DH
    ./easyrsa gen-dh
    
    # Создаем CRL
    ./easyrsa gen-crl
    
    # Копируем в /etc/openvpn
    cp -r pki/* /etc/openvpn/pki/
    
    # Создаем тестовых клиентов
    for client in test-client test-client2; do
        ./easyrsa build-client-full $client nopass
    done
    
    echo "PKI initialized!"
fi

# Создаем CCD файлы для тестовых клиентов
mkdir -p /etc/openvpn/ccd
if [ ! -f /etc/openvpn/ccd/test-client ]; then
    echo "ifconfig-push 10.8.0.10 255.255.255.0" > /etc/openvpn/ccd/test-client
fi
if [ ! -f /etc/openvpn/ccd/test-client2 ]; then
    echo "ifconfig-push 10.8.0.11 255.255.255.0" > /etc/openvpn/ccd/test-client2
fi

# Права на логи
touch /var/log/openvpn/server.log
chmod 666 /var/log/openvpn/server.log

# Запускаем OpenVPN
echo "Starting OpenVPN server..."
exec openvpn --config /etc/openvpn/server.conf
```

### docker/openvpn-server/scripts/client-connect

```python
#!/usr/bin/env python3
"""
Скрипт client-connect для OpenVPN в Docker окружении.
Вызывается при подключении клиента.
"""
import os
import sys

# Добавляем путь к проекту
sys.path.insert(0, '/opt/openvpn-logserver')

# Устанавливаем переменные окружения для БД
os.environ.setdefault('DB_PASSWORD', os.getenv('DB_PASSWORD', ''))

from collector.client_connect import main

if __name__ == '__main__':
    sys.exit(main())
```

### docker/openvpn-server/scripts/client-disconnect

```python
#!/usr/bin/env python3
"""
Скрипт client-disconnect для OpenVPN в Docker окружении.
Вызывается при отключении клиента.
"""
import os
import sys

# Добавляем путь к проекту
sys.path.insert(0, '/opt/openvpn-logserver')

# Устанавливаем переменные окружения для БД
os.environ.setdefault('DB_PASSWORD', os.getenv('DB_PASSWORD', ''))

from collector.client_disconnect import main

if __name__ == '__main__':
    sys.exit(main())
```

## Dockerfile для OpenVPN клиента

### docker/openvpn-client/Dockerfile

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    openvpn \
    iputils-ping \
    curl \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY docker/openvpn-client/client.conf /etc/openvpn/client.conf.template
COPY docker/openvpn-client/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

### docker/openvpn-client/client.conf

```conf
client
dev tun
proto udp

remote openvpn-server 1194

resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server
cipher AES-256-GCM
auth SHA256

verb 3
```

### docker/openvpn-client/entrypoint.sh

```bash
#!/bin/bash
set -e

CLIENT_NAME=${CLIENT_NAME:-test-client}

echo "Setting up OpenVPN client: $CLIENT_NAME"

# Ждем пока сервер создаст сертификаты
sleep 5

# Копируем конфигурацию
cp /etc/openvpn/client.conf.template /etc/openvpn/client.conf

# Копируем сертификаты с сервера (в реальном сценарии - через volumes)
if [ -f /etc/openvpn/pki/ca.crt ]; then
    cp /etc/openvpn/pki/ca.crt /etc/openvpn/
    cp /etc/openvpn/pki/issued/$CLIENT_NAME.crt /etc/openvpn/client.crt
    cp /etc/openvpn/pki/private/$CLIENT_NAME.key /etc/openvpn/client.key
fi

echo "Starting OpenVPN client..."
exec openvpn --config /etc/openvpn/client.conf
```

## Инициализация БД

### docker/mysql/init.sql

```sql
-- Создание базы и пользователя (делается через ENV в compose)
-- USE openvpn_logs;

-- Таблица accounts
CREATE TABLE IF NOT EXISTS accounts (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cn VARCHAR(255) NOT NULL,
    valid_from DATETIME,
    valid_to DATETIME,
    is_revoked BOOLEAN DEFAULT FALSE,
    revoked_at DATETIME,
    has_ccd BOOLEAN DEFAULT FALSE,
    ccd_updated_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_cn (cn),
    INDEX idx_valid_to (valid_to),
    INDEX idx_is_revoked (is_revoked),
    INDEX idx_has_ccd (has_ccd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица sessions
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED NOT NULL,
    connected_at DATETIME NOT NULL,
    disconnected_at DATETIME,
    source_ip VARCHAR(45),
    country VARCHAR(100),
    city VARCHAR(100),
    bytes_sent BIGINT UNSIGNED DEFAULT 0,
    bytes_received BIGINT UNSIGNED DEFAULT 0,
    virtual_ip VARCHAR(45),
    status ENUM('active', 'closed') DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account_id (account_id),
    INDEX idx_connected_at (connected_at),
    INDEX idx_status (status),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица connection_attempts
CREATE TABLE IF NOT EXISTS connection_attempts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED,
    attempted_at DATETIME NOT NULL,
    source_ip VARCHAR(45) NOT NULL,
    cert_cn VARCHAR(255),
    failure_reason VARCHAR(255),
    failure_type ENUM('auth_failed', 'cert_revoked', 'cert_expired', 'ccd_missing', 'tls_error', 'other') DEFAULT 'other',
    details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account_id (account_id),
    INDEX idx_attempted_at (attempted_at),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Таблица geoip_cache
CREATE TABLE IF NOT EXISTS geoip_cache (
    ip VARCHAR(45) PRIMARY KEY,
    country VARCHAR(100),
    country_code VARCHAR(2),
    city VARCHAR(100),
    cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## Использование

### Запуск окружения

```bash
# Переходим в директорию docker
cd docker

# Создаем файл конфигурации БД для Docker
mkdir -p ../config
cat > ../config/database.yaml <<EOF
database:
  host: mysql
  port: 3306
  name: openvpn_logs
  user: openvpn
  password: \${DB_PASSWORD}
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600
  charset: utf8mb4
EOF

# Запускаем основные сервисы
docker-compose up -d

# Проверяем статус
docker-compose ps

# Логи
docker-compose logs -f

# Запускаем клиента для тестирования
docker-compose --profile client up -d openvpn-client
```

### Применение миграций в Docker

```bash
# Запускаем миграции через контейнер web
docker-compose exec web bash -c "cd database && alembic upgrade head"

# Или с использованием DATABASE_URL
docker-compose exec -e DATABASE_URL="mysql+pymysql://openvpn:openvpn_password@mysql:3306/openvpn_logs" web bash -c "cd database && alembic upgrade head"
```

### Доступ к сервисам

| Сервис | URL | Описание |
|--------|-----|----------|
| Web App | http://localhost:8000 | Приложение мониторинга |
| API Docs | http://localhost:8000/docs | Swagger UI |
| MySQL | localhost:3306 | База данных |
| OpenVPN Mgmt | localhost:7505 | Management interface |

### Тестирование подключения

```bash
# Подключаем клиента
docker-compose exec openvpn-client openvpn --config /etc/openvpn/client.conf

# Проверяем сессию в БД
docker-compose exec mysql mysql -u openvpn -popenvpn_password openvpn_logs -e "SELECT * FROM sessions;"

# Проверяем в Web UI
curl http://localhost:8000/api/v1/sessions/active
```

### Отладка

```bash
# Вход в контейнер приложения
docker-compose exec web bash

# Вход в контейнер OpenVPN сервера
docker-compose exec openvpn-server bash

# Просмотр логов OpenVPN
docker-compose exec openvpn-server tail -f /var/log/openvpn/server.log

# Проверка скриптов
docker-compose exec openvpn-server python3 /etc/openvpn/scripts/client-connect
```

### Пересборка

```bash
# Пересобрать все
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d

# Пересобрать только приложение
docker-compose up -d --build web
```

## Отличия от production

| Аспект | Docker (dev) | Production |
|--------|--------------|------------|
| Конфигурация | `config/database.yaml` монтируется | `config/database.yaml` в `/opt/openvpn-logserver/config/` |
| Переменные окружения | Через `.env` и `environment` | Через systemd или `/etc/environment` |
| Безопасность | Упрощенная | Полная (SELinux, AppArmor) |
| SSL/TLS | Отсутствует | Nginx reverse proxy с SSL |
| Логирование | stdout + файлы | syslog + файлы + rotation |
