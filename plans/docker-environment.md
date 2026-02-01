# Docker окружение для разработки

## Архитектура контейнеров

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Docker Compose Network                              │
│                                                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐           │
│  │   openvpn-server │  │   app-server     │  │  openvpn-client  │           │
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
│                    │      mysql-db        │                                  │
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
├──
├── app/                         # Приложение
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── requirements.txt
│
├── openvpn-server/              # OpenVPN сервер
│   ├── Dockerfile
│   ├── server.conf
│   ├── entrypoint.sh
│   └── scripts/
│       ├── client-connect
│       ├── client-disconnect
│       └── setup-pki.sh
│
├── openvpn-client/              # OpenVPN клиент (для тестов)
│   ├── Dockerfile
│   ├── client.conf.template
│   └── entrypoint.sh
│
├── mysql/                       # База данных
│   ├── init.sql                 # Инициализация схемы
│   └── docker-entrypoint-initdb.d/
│
└── shared/                      # Общие данные
    ├── pki/                     # PKI (генерируется)
    ├── ccd/                     # Client configs
    └── logs/                    # Логи
```

## Docker Compose

### docker-compose.yml

```yaml
version: '3.8'

services:
  # MySQL Database
  mysql:
    image: mysql:8.0
    container_name: ovpn-mysql
    environment:
      MYSQL_ROOT_PASSWORD: rootpass
      MYSQL_DATABASE: openvpn_logs
      MYSQL_USER: ovpn_collector
      MYSQL_PASSWORD: collectorpass
    volumes:
      - mysql_data:/var/lib/mysql
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    ports:
      - "3306:3306"
    networks:
      - ovpn-network
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  # OpenVPN Server
  openvpn-server:
    build:
      context: ./openvpn-server
      dockerfile: Dockerfile
    container_name: ovpn-server
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.ip_forward=1
    ports:
      - "1194:1194/udp"
      - "7505:7505"  # Management interface
    volumes:
      - shared_pki:/etc/openvpn/pki
      - shared_ccd:/etc/openvpn/ccd
      - shared_logs:/var/log/openvpn
      - ./openvpn-server/scripts:/etc/openvpn/scripts:ro
    networks:
      - ovpn-network
    depends_on:
      mysql:
        condition: service_healthy
    environment:
      DB_HOST: mysql
      DB_NAME: openvpn_logs
      DB_USER: ovpn_collector
      DB_PASS: collectorpass

  # Application Server
  app:
    build:
      context: ./app
      dockerfile: Dockerfile
    container_name: ovpn-app
    ports:
      - "8000:8000"
    volumes:
      - shared_pki:/etc/openvpn/pki:ro
      - shared_ccd:/etc/openvpn/ccd:ro
      - shared_logs:/var/log/openvpn:ro
      - ../:/opt/openvpn-logserver:ro  # Монтируем код для разработки
    networks:
      - ovpn-network
    depends_on:
      mysql:
        condition: service_healthy
      openvpn-server:
        condition: service_started
    environment:
      DB_HOST: mysql
      DB_NAME: openvpn_logs
      DB_USER: ovpn_collector
      DB_PASS: collectorpass
      APP_ENV: development
    command: uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

  # OpenVPN Client (для тестирования)
  openvpn-client:
    build:
      context: ./openvpn-client
      dockerfile: Dockerfile
    container_name: ovpn-client
    cap_add:
      - NET_ADMIN
    sysctls:
      - net.ipv4.ip_forward=1
    networks:
      - ovpn-network
    depends_on:
      - openvpn-server
    environment:
      CLIENT_NAME: test-client
    profiles:
      - client  # Запускать явно: docker-compose --profile client up

volumes:
  mysql_data:
  shared_pki:
  shared_ccd:
  shared_logs:

networks:
  ovpn-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### .env

```bash
# Database
MYSQL_ROOT_PASSWORD=rootpass
MYSQL_DATABASE=openvpn_logs
MYSQL_USER=ovpn_collector
MYSQL_PASSWORD=collectorpass

# App
APP_ENV=development
APP_SECRET_KEY=dev-secret-key-change-in-production

# OpenVPN
OVPN_SERVER_NET=10.8.0.0
OVPN_SERVER_MASK=255.255.255.0
```

## Dockerfile для приложения

### app/Dockerfile

```dockerfile
FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /opt/openvpn-logserver

# Копируем requirements
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Открываем порт
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

### app/requirements.txt

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
jinja2==3.1.2
sqlalchemy==2.0.23
aiomysql==0.2.0
pydantic==2.5.0
pydantic-settings==2.1.0
python-multipart==0.0.6
pyyaml==6.0.1
requests==2.31.0
cryptography==41.0.7
pyopenssl==23.3.0
mysqlclient==2.2.1
```

### app/entrypoint.sh

```bash
#!/bin/bash
set -e

echo "Waiting for MySQL..."
while ! nc -z mysql 3306; do
  sleep 1
done
echo "MySQL is up!"

# Применяем миграции (если есть)
# alembic upgrade head

echo "Starting application..."
exec "$@"
```

## Dockerfile для OpenVPN сервера

### openvpn-server/Dockerfile

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
    net-tools \
    iputils-ping \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python библиотеки для скриптов
RUN pip3 install requests --break-system-packages

# Создаем директории
RUN mkdir -p /etc/openvpn/pki /etc/openvpn/ccd /etc/openvpn/scripts /var/log/openvpn

# Копируем конфигурацию
COPY server.conf /etc/openvpn/server.conf
COPY entrypoint.sh /entrypoint.sh
COPY scripts/ /etc/openvpn/scripts/

RUN chmod +x /entrypoint.sh /etc/openvpn/scripts/*

# PKI будет создан в entrypoint
VOLUME ["/etc/openvpn/pki", "/etc/openvpn/ccd", "/var/log/openvpn"]

EXPOSE 1194/udp 7505/tcp

ENTRYPOINT ["/entrypoint.sh"]
```

### openvpn-server/server.conf

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

### openvpn-server/entrypoint.sh

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

### openvpn-server/scripts/client-connect

```python
#!/usr/bin/env python3
import os
import sys
import MySQLdb
import requests

def get_geoip(ip):
    """Простой GeoIP без кэша для демо"""
    try:
        resp = requests.get(f'http://ip-api.com/json/{ip}', timeout=2)
        data = resp.json()
        if data.get('status') == 'success':
            return data.get('country'), data.get('city')
    except:
        pass
    return None, None

def main():
    cn = os.environ.get('common_name')
    source_ip = os.environ.get('trusted_ip')
    virtual_ip = os.environ.get('ifconfig_pool_remote_ip')
    
    if not cn:
        sys.exit(0)
    
    try:
        db = MySQLdb.connect(
            host=os.environ.get('DB_HOST', 'mysql'),
            user=os.environ.get('DB_USER', 'ovpn_collector'),
            passwd=os.environ.get('DB_PASS', 'collectorpass'),
            db=os.environ.get('DB_NAME', 'openvpn_logs')
        )
        cursor = db.cursor()
        
        # Создаем/получаем account
        cursor.execute(
            "INSERT INTO accounts (cn) VALUES (%s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
            (cn,)
        )
        account_id = cursor.lastrowid
        
        # GeoIP
        country, city = get_geoip(source_ip) if source_ip else (None, None)
        
        # Создаем сессию
        cursor.execute("""
            INSERT INTO sessions (account_id, connected_at, source_ip, country, city, virtual_ip, status)
            VALUES (%s, NOW(), %s, %s, %s, %s, 'active')
        """, (account_id, source_ip, country, city, virtual_ip))
        
        db.commit()
        cursor.close()
        db.close()
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        # Не блокируем подключение
    
    sys.exit(0)

if __name__ == '__main__':
    main()
```

### openvpn-server/scripts/client-disconnect

```python
#!/usr/bin/env python3
import os
import sys
import MySQLdb

def main():
    cn = os.environ.get('common_name')
    bytes_sent = int(os.environ.get('bytes_sent', 0))
    bytes_received = int(os.environ.get('bytes_received', 0))
    
    if not cn:
        sys.exit(0)
    
    try:
        db = MySQLdb.connect(
            host=os.environ.get('DB_HOST', 'mysql'),
            user=os.environ.get('DB_USER', 'ovpn_collector'),
            passwd=os.environ.get('DB_PASS', 'collectorpass'),
            db=os.environ.get('DB_NAME', 'openvpn_logs')
        )
        cursor = db.cursor()
        
        cursor.execute("""
            UPDATE sessions s
            JOIN accounts a ON a.id = s.account_id
            SET s.disconnected_at = NOW(),
                s.status = 'closed',
                s.bytes_sent = %s,
                s.bytes_received = %s
            WHERE a.cn = %s AND s.status = 'active'
            ORDER BY s.connected_at DESC
            LIMIT 1
        """, (bytes_sent, bytes_received, cn))
        
        db.commit()
        cursor.close()
        db.close()
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
    
    sys.exit(0)

if __name__ == '__main__':
    main()
```

## Dockerfile для OpenVPN клиента

### openvpn-client/Dockerfile

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    openvpn \
    iputils-ping \
    curl \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY client.conf.template /etc/openvpn/client.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

### openvpn-client/client.conf.template

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

### openvpn-client/entrypoint.sh

```bash
#!/bin/bash
set -e

CLIENT_NAME=${CLIENT_NAME:-test-client}

echo "Setting up OpenVPN client: $CLIENT_NAME"

# Ждем пока сервер создаст сертификаты
sleep 5

# Копируем конфигурацию
sed "s/CLIENT_NAME/$CLIENT_NAME/g" /etc/openvpn/client.conf.template > /etc/openvpn/client.conf

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

### mysql/init.sql

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

# Запускаем основные сервисы
docker-compose up -d

# Проверяем статус
docker-compose ps

# Логи
docker-compose logs -f

# Запускаем клиента для тестирования
docker-compose --profile client up -d openvpn-client
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
docker-compose exec mysql mysql -u ovpn_collector -pcollectorpass openvpn_logs -e "SELECT * FROM sessions;"

# Проверяем в Web UI
curl http://localhost:8000/api/v1/sessions/active
```

### Отладка

```bash
# Вход в контейнер приложения
docker-compose exec app bash

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
docker-compose up -d --build app
```
