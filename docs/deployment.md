# Развертывание и Systemd сервисы

## Быстрый старт для root

Минимальная установка для работы под пользователем root.

### Требования
- Debian/Ubuntu
- Python 3.9+
- MySQL 8.0+

### Установка

```bash
# Установка зависимостей
apt update
apt install -y python3 python3-pip mysql-server git

# Клонирование репозитория
cd /opt
git clone <repository-url> openvpn-logserver
cd openvpn-logserver

# Установка Python зависимостей
pip install -r database/requirements.txt
pip install -r web/requirements.txt
pip install -r collector/requirements.txt

# Настройка базы данных
mysql -u root -p <<EOF
CREATE DATABASE IF NOT EXISTS openvpn_logs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'openvpn_user'@'localhost' IDENTIFIED BY 'СМЕНИТЕ_ПАРОЛЬ_БД';
GRANT ALL PRIVILEGES ON openvpn_logs.* TO 'openvpn_user'@'localhost';
FLUSH PRIVILEGES;
EOF

# Применение миграций
cd database && alembic upgrade head && cd ..

# Конфигурация: заполнить config/*.yaml в каталоге проекта.
# ВАЖНО: core/config.py читает ТОЛЬКО <каталог проекта>/config —
# отдельный /etc/openvpn-logserver/config приложение не увидит.
# Альтернатива: не создавать yaml вовсе и задать всё через ENV
# (DATABASE_URL, WEB_AUTH_USERNAME, WEB_AUTH_PASSWORD_HASH) —
# файлы конфигурации не обязательны.
cp config/database.yaml.example config/database.yaml
cp config/auth.yaml.example     config/auth.yaml
cp config/web.yaml.example      config/web.yaml

# Создание директории для логов
mkdir -p /opt/openvpn-logserver/logs
```

### 2. Подключение скриптов к OpenVPN

Скрипты `client-connect` и `client-disconnect` фиксируют подключения в БД.

#### 2.1 Создание wrapper-скриптов

Вместо прямого копирования Python-файлов создаём wrapper-скрипты, которые:
- Устанавливают правильный `PYTHONPATH`
- Вызывают функции из оригинальных модулей

```bash
# Создаем директорию для скриптов
mkdir -p /etc/openvpn/scripts

# Создаем wrapper для client-connect
cat > /etc/openvpn/scripts/client-connect <<'EOF'
#!/usr/bin/env python3
"""
Wrapper для client-connect скрипта OpenVPN.
Вызывается при подключении клиента.
"""
import sys
import os

# Добавляем путь к проекту для импорта модулей
sys.path.insert(0, '/opt/openvpn-logserver')

from collector.client_connect import main

if __name__ == '__main__':
    sys.exit(main())
EOF

# Создаем wrapper для client-disconnect
cat > /etc/openvpn/scripts/client-disconnect <<'EOF'
#!/usr/bin/env python3
"""
Wrapper для client-disconnect скрипта OpenVPN.
Вызывается при отключении клиента.
"""
import sys
import os

# Добавляем путь к проекту для импорта модулей
sys.path.insert(0, '/opt/openvpn-logserver')

from collector.client_disconnect import main

if __name__ == '__main__':
    sys.exit(main())
EOF

# Права на выполнение
chmod +x /etc/openvpn/scripts/client-connect
chmod +x /etc/openvpn/scripts/client-disconnect
```

#### 2.2 Настройка OpenVPN

Добавьте в `/etc/openvpn/server.conf`:

```conf
# ОБЯЗАТЕЛЬНО: без script-security 2 OpenVPN 2.6 не исполняет внешние
# скрипты — хуки молча не отработают, и сессии не попадут в БД
script-security 2

# Скрипты логирования
client-connect /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# Нужен для обнаружения оборванных сессий (session_cleanup)
management /run/openvpn/mgmt.sock unix
```

`common_name`, `trusted_ip`, `ifconfig_pool_remote_ip` и `tls_serial_0` OpenVPN
передаёт хукам сам — перечислять их через `setenv-safe` не нужно и вредно:
директива добавляет к имени префикс `OPENVPN_`.

Полный список требований к server.conf — [openvpn-setup.md](openvpn-setup.md).

Перезапустите OpenVPN:
```bash
systemctl restart openvpn@server
```

#### 2.3 Проверка

Подключитесь к VPN и проверьте:
```bash
# В БД должна появиться запись
mysql -u root -p openvpn_logs -e "SELECT * FROM sessions WHERE status='active';"

# Логи скриптов
journalctl -u openvpn@server -f
```

### 3. Настройка конфигурации

Отредактируйте `config/database.yaml` в каталоге проекта:
- `password` — пароль для подключения к БД

Отредактируйте `config/auth.yaml`:
- `username` и `password_hash` (bcrypt) для доступа к Web UI.
  Plaintext-поле `password` поддержано как legacy и выводит предупреждение.
  Сгенерировать хеш:
  `python3 -c "import bcrypt; print(bcrypt.hashpw(b'ПАРОЛЬ', bcrypt.gensalt()).decode())"`

Отредактируйте `config/web.yaml`:
- `debug: false` для прода (иначе будут открыты `/docs` и `/openapi.json`)
- `cors.allow_origins` — список доменов; при `["*"]` CORS отключается целиком

### 4. Запуск

**Вручную:**
```bash
uvicorn web.main:app --host 0.0.0.0 --port 8000
```

**Через systemd:**
```bash
# Копирование unit-файлов
cp systemd/openvpn-web.service /etc/systemd/system/
cp systemd/openvpn-sync.service /etc/systemd/system/
cp systemd/openvpn-sync.timer /etc/systemd/system/

# Обновление systemd и запуск
systemctl daemon-reload
systemctl enable --now openvpn-web
systemctl enable --now openvpn-sync.timer
```

### 5. Проверка

```bash
# Статус сервисов
systemctl status openvpn-web
systemctl list-timers openvpn-sync.timer

# Логи
journalctl -u openvpn-web -f

# API check
curl -u admin:СМЕНИТЕ_ПАРОЛЬ_АДМИНА http://localhost:8000/api/v1/stats/overview
```

---

## Развертывание с изоляцией (опционально)

Полная инструкция с созданием отдельного пользователя и настройкой безопасности.

### Структура установки

```
/opt/openvpn-logserver/          # Корневая директория
├── venv/                        # Python virtual environment
├── collector/                   # Модуль сбора данных
├── web/                         # Web приложение
├── core/                        # Общие модули (модели, БД)
├── database/                    # Миграции Alembic
├── config/                      # Конфигурационные файлы
│   ├── database.yaml            # Конфигурация БД
│   ├── auth.yaml                # Учетные данные
│   └── web.yaml                 # Конфигурация web-приложения
├── logs/                        # Логи приложения
└── systemd/                     # Unit файлы (копируются в /etc/systemd/system/)
```

### Пользователи и права

```bash
# Создать системного пользователя
sudo useradd -r -s /bin/false -d /opt/openvpn-logserver ovpn-logserver

# Создать группу для доступа к OpenVPN файлам
sudo groupadd ovpn-readers
sudo usermod -a -G ovpn-readers ovpn-logserver

# Создать директорию
sudo mkdir -p /opt/openvpn-logserver

# Владелец директории
sudo chown -R ovpn-logserver:ovpn-logserver /opt/openvpn-logserver
```

### Установка

#### 1. Подготовка системы

```bash
# Установить зависимости
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mysql-server git
```

#### 2. Клонирование и настройка

```bash
# Клонировать репозиторий (замените URL на актуальный)
cd /opt
sudo git clone <repository-url> openvpn-logserver
sudo chown -R ovpn-logserver:ovpn-logserver /opt/openvpn-logserver

# Переходим в директорию проекта
cd /opt/openvpn-logserver

# Создать virtual environment
sudo -u ovpn-logserver python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r database/requirements.txt
pip install -r web/requirements.txt
pip install -r collector/requirements.txt

# Создать директорию для логов
sudo -u ovpn-logserver mkdir -p logs
```

#### 3. Настройка базы данных

```bash
# Создать базу данных и пользователя
sudo mysql -u root <<EOF
CREATE DATABASE IF NOT EXISTS openvpn_logs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'openvpn_user'@'localhost' IDENTIFIED BY 'СМЕНИТЕ_ПАРОЛЬ_БД';
GRANT ALL PRIVILEGES ON openvpn_logs.* TO 'openvpn_user'@'localhost';
FLUSH PRIVILEGES;
EOF
```

#### 4. Конфигурация

##### 4.1 Создание конфигурационных файлов

```bash
# Создать директорию для конфигов
sudo mkdir -p /opt/openvpn-logserver/config

# Создать конфигурацию БД
sudo tee /opt/openvpn-logserver/config/database.yaml <<EOF
# Конфигурация базы данных OpenVPN LogServer
# Все настройки хранятся в открытом виде в YML файлах

database:
  # Параметры подключения к MySQL
  host: localhost
  port: 3306
  name: openvpn_logs
  user: openvpn_user
  password: СМЕНИТЕ_ПАРОЛЬ_БД  # Пароль в открытом виде

  # Параметры пула соединений
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600

  # Дополнительные параметры подключения
  charset: utf8mb4
EOF

# Создать конфигурацию аутентификации
sudo tee /opt/openvpn-logserver/config/auth.yaml <<EOF
# Конфигурация аутентификации OpenVPN LogServer
# Учетные данные для доступа к системе

auth:
  web:
    username: admin
    password: СМЕНИТЕ_ПАРОЛЬ_АДМИНА  # Пароль в открытом виде
EOF

# Создать конфигурацию web приложения
sudo tee /opt/openvpn-logserver/config/web.yaml <<EOF
# Конфигурация Web приложения OpenVPN LogServer

# Настройки базы данных
# URL подключения формируется автоматически из database.yaml
database:
  # Пул соединений
  pool_size: 10
  max_overflow: 20

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
EOF

# Установить права на конфиги
sudo chmod 640 /opt/openvpn-logserver/config/*.yaml
sudo chown ovpn-logserver:ovpn-logserver /opt/openvpn-logserver/config/*.yaml
```

#### 5. Применение миграций

```bash
# Применить миграции
cd database && alembic upgrade head && cd ..
```

#### 6. Настройка OpenVPN скриптов

```bash
# Создать директорию для скриптов OpenVPN
sudo mkdir -p /etc/openvpn/scripts

# Скопировать скрипты client-connect и client-disconnect
sudo tee /etc/openvpn/scripts/client-connect <<'EOF'
#!/opt/openvpn-logserver/venv/bin/python
"""
Скрипт client-connect для OpenVPN.
Вызывается при подключении клиента.
"""
import os
import sys

# Добавляем путь к проекту
sys.path.insert(0, '/opt/openvpn-logserver')

from collector.client_connect import main

if __name__ == '__main__':
    sys.exit(main())
EOF

sudo tee /etc/openvpn/scripts/client-disconnect <<'EOF'
#!/opt/openvpn-logserver/venv/bin/python
"""
Скрипт client-disconnect для OpenVPN.
Вызывается при отключении клиента.
"""
import os
import sys

# Добавляем путь к проекту
sys.path.insert(0, '/opt/openvpn-logserver')

from collector.client_disconnect import main

if __name__ == '__main__':
    sys.exit(main())
EOF

# Установить права на скрипты
sudo chmod 755 /etc/openvpn/scripts/client-connect
sudo chmod 755 /etc/openvpn/scripts/client-disconnect
sudo chown root:ovpn-logserver /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
```

#### 7. Настройка OpenVPN

Добавьте в конфигурацию OpenVPN (`/etc/openvpn/server.conf`):

```conf
# Скрипты подключения/отключения
client-connect /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# Логирование
log-append /var/log/openvpn/server.log
verb 3
status /var/log/openvpn/status.log
```

Перезапустите OpenVPN:
```bash
sudo systemctl restart openvpn-server@server
```

## Systemd сервисы (для изолированного развертывания)

### 1. openvpn-web.service

Web приложение.

```bash
# Создать unit-файл
sudo tee /etc/systemd/system/openvpn-web.service <<'EOF'
[Unit]
Description=OpenVPN LogServer Web Interface
Documentation=https://github.com/yourorg/openvpn-logserver
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=simple
User=ovpn-logserver
Group=ovpn-logserver
WorkingDirectory=/opt/openvpn-logserver

Environment=PYTHONPATH=/opt/openvpn-logserver
Environment=LOG_LEVEL=INFO

ExecStart=/opt/openvpn-logserver/venv/bin/uvicorn web.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2

Restart=always
RestartSec=5
StartLimitInterval=60s
StartLimitBurst=3

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/openvpn-logserver/logs
ReadOnlyPaths=/opt/openvpn-logserver/config

[Install]
WantedBy=multi-user.target
EOF
```

### 2. openvpn-sync.timer + openvpn-sync.service

Периодические задачи синхронизации (сертификаты, CRL, CCD).

```bash
# Timer
sudo tee /etc/systemd/system/openvpn-sync.timer <<'EOF'
[Unit]
Description=OpenVPN Data Sync Timer
Documentation=https://github.com/yourorg/openvpn-logserver

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

# Service
sudo tee /etc/systemd/system/openvpn-sync.service <<'EOF'
[Unit]
Description=OpenVPN Data Sync
Documentation=https://github.com/yourorg/openvpn-logserver
After=mysql.service

[Service]
Type=oneshot
User=ovpn-logserver
Group=ovpn-logserver
WorkingDirectory=/opt/openvpn-logserver

Environment=PYTHONPATH=/opt/openvpn-logserver

ExecStart=/opt/openvpn-logserver/venv/bin/python -c "
import sys
sys.path.insert(0, '/opt/openvpn-logserver')
from collector.cert_sync import sync_certificates
from collector.crl_checker import check_crl
from collector.ccd_checker import check_ccd
from core.database import SessionLocal
db = SessionLocal()
try:
    sync_certificates(db)
    check_crl(db)
    check_ccd(db)
finally:
    db.close()
"

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/opt/openvpn-logserver/config
ReadOnlyPaths=/etc/openvpn
EOF
```

## Nginx (Reverse Proxy)

```bash
# Создать конфигурацию Nginx
sudo tee /etc/nginx/sites-available/openvpn-logserver <<'EOF'
server {
    listen 80;
    server_name vpn-monitor.example.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name vpn-monitor.example.com;

    ssl_certificate /etc/ssl/certs/vpn-monitor.crt;
    ssl_certificate_key /etc/ssl/private/vpn-monitor.key;

    # Basic Auth
    auth_basic "OpenVPN Monitor";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (for future real-time features)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Static files (optional - for better performance)
    location /static {
        alias /opt/openvpn-logserver/web/static;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Активировать сайт
sudo ln -sf /etc/nginx/sites-available/openvpn-logserver /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Создание пользователя basic auth:
```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin
```

## Управление сервисами

```bash
# Перезагрузить systemd
sudo systemctl daemon-reload

# Запустить web
sudo systemctl enable --now openvpn-web

# Запустить таймер синхронизации
sudo systemctl enable --now openvpn-sync.timer

# Проверить статус
sudo systemctl status openvpn-web
sudo systemctl list-timers openvpn-sync.timer

# Просмотр логов
sudo journalctl -u openvpn-web -f
sudo journalctl -u openvpn-sync -f
```

## Мониторинг

### Health Check

```bash
# Проверка web приложения
curl -u admin:СМЕНИТЕ_ПАРОЛЬ_АДМИНА http://localhost:8000/api/v1/stats/overview

# Проверка БД
mysql -u openvpn_user -p -e "SELECT 1 FROM accounts LIMIT 1;" openvpn_logs
```

### Метрики (опционально)

```python
# Добавить endpoint для Prometheus
@app.get("/metrics")
async def metrics():
    return {
        "active_sessions": await get_active_session_count(),
        "total_accounts": await get_total_account_count(),
    }
```

## Backup

```bash
#!/bin/bash
# /opt/openvpn-logserver/scripts/backup.sh

BACKUP_DIR="/backup/openvpn-logserver"
DATE=$(date +%Y%m%d_%H%M%S)

# Создать директорию для бэкапов
mkdir -p "$BACKUP_DIR"

# Backup database
mysqldump -u root -p openvpn_logs > "$BACKUP_DIR/db_$DATE.sql"

# Backup config
cp -r /opt/openvpn-logserver/config "$BACKUP_DIR/config_$DATE"

# Cleanup old backups (keep 30 days)
find "$BACKUP_DIR" -name "*.sql" -mtime +30 -delete
find "$BACKUP_DIR" -name "config_*" -mtime +30 -exec rm -rf {} \;
```

## Обновление

```bash
#!/bin/bash
# /opt/openvpn-logserver/scripts/update.sh

cd /opt/openvpn-logserver

# Backup
./scripts/backup.sh

# Stop services
sudo systemctl stop openvpn-web openvpn-sync.timer

# Update code
sudo -u ovpn-logserver git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r database/requirements.txt --upgrade
pip install -r web/requirements.txt --upgrade
pip install -r collector/requirements.txt --upgrade

# Run migrations
cd database && alembic upgrade head && cd ..

# Start services
sudo systemctl start openvpn-web openvpn-sync.timer

# Check status
sudo systemctl status openvpn-web
```

## Порядок развертывания (кратко)

1. **Установить зависимости** - Python, MySQL, Git
2. **Подключить скрипты к OpenVPN** - скопировать `client-connect` и `client-disconnect`, настроить `server.conf`
3. **Создать файл `config/database.yaml`** - настройки БД с паролем в открытом виде
4. **Создать файл `config/auth.yaml`** - учетные данные для доступа
5. **Применить миграции** - `cd database && alembic upgrade head`
6. **Запустить компоненты** - Web UI и systemd таймеры
