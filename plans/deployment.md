# Развертывание и Systemd сервисы

## Структура установки

```
/opt/openvpn-logserver/          # Корневая директория
├── venv/                        # Python virtual environment
├── collector/                   # Модуль сбора данных
├── web/                         # Web приложение
├── config/                      # Конфигурационные файлы
│   ├── collector.yaml
│   └── web.yaml
├── logs/                        # Логи приложения
└── systemd/                     # Unit файлы (копируются в /etc/systemd/system/)
```

## Пользователи и права

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

## Установка

### 1. Подготовка системы

```bash
# Установить зависимости
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mysql-server
```

### 2. Клонирование и настройка

```bash
cd /opt/openvpn-logserver

# Создать virtual environment
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r collector/requirements.txt
pip install -r web/requirements.txt

# Инициализировать БД
alembic upgrade head
```

### 3. Конфигурация

```bash
# Создать директорию для конфигов
sudo mkdir -p /etc/openvpn-logserver

# Скопировать и настроить конфиги
sudo cp config/collector.yaml /etc/openvpn-logserver/
sudo cp config/web.yaml /etc/openvpn-logserver/

# Установить пароль БД
sudo touch /etc/openvpn-logserver/db_password
sudo chmod 600 /etc/openvpn-logserver/db_password
sudo chown ovpn-logserver:ovpn-logserver /etc/openvpn-logserver/db_password
echo "your_password" | sudo tee /etc/openvpn-logserver/db_password
```

## Systemd сервисы

### 1. openvpn-collector.service

Основной демон сбора логов.

```ini
# /etc/systemd/system/openvpn-collector.service
[Unit]
Description=OpenVPN Log Collector
Documentation=https://github.com/yourorg/openvpn-logserver
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=simple
User=ovpn-logserver
Group=ovpn-logserver
WorkingDirectory=/opt/openvpn-logserver

Environment=PYTHONPATH=/opt/openvpn-logserver
Environment=CONFIG_PATH=/etc/openvpn-logserver/collector.yaml
Environment=DB_PASSWORD_FILE=/etc/openvpn-logserver/db_password
Environment=LOG_LEVEL=INFO

ExecStart=/opt/openvpn-logserver/venv/bin/python -m collector.log_watcher
ExecReload=/bin/kill -HUP $MAINPID

Restart=always
RestartSec=10
StartLimitInterval=60s
StartLimitBurst=3

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/openvpn-logserver/logs
ReadOnlyPaths=/etc/openvpn-logserver
ReadOnlyPaths=/var/log/openvpn
ReadOnlyPaths=/etc/openvpn

[Install]
WantedBy=multi-user.target
```

### 2. openvpn-web.service

Web приложение.

```ini
# /etc/systemd/system/openvpn-web.service
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
Environment=CONFIG_PATH=/etc/openvpn-logserver/web.yaml
Environment=DB_PASSWORD_FILE=/etc/openvpn-logserver/db_password
Environment=LOG_LEVEL=INFO

ExecStart=/opt/openvpn-logserver/venv/bin/uvicorn web.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2 \
    --access-log \
    --error-log

Restart=always
RestartSec=5
StartLimitInterval=60s
StartLimitBurst=3

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/openvpn-logserver/logs
ReadOnlyPaths=/etc/openvpn-logserver

[Install]
WantedBy=multi-user.target
```

### 3. openvpn-sync.timer + openvpn-sync.service

Периодические задачи синхронизации.

```ini
# /etc/systemd/system/openvpn-sync.timer
[Unit]
Description=OpenVPN Data Sync Timer
Documentation=https://github.com/yourorg/openvpn-logserver

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/openvpn-sync.service
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
Environment=CONFIG_PATH=/etc/openvpn-logserver/collector.yaml
Environment=DB_PASSWORD_FILE=/etc/openvpn-logserver/db_password

ExecStart=/opt/openvpn-logserver/venv/bin/python -m collector.sync_all

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/etc/openvpn-logserver
ReadOnlyPaths=/etc/openvpn
```

## Nginx (Reverse Proxy)

```nginx
# /etc/nginx/sites-available/openvpn-logserver
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

# Запустить коллектор
sudo systemctl enable --now openvpn-collector

# Запустить web
sudo systemctl enable --now openvpn-web

# Запустить таймер синхронизации
sudo systemctl enable --now openvpn-sync.timer

# Проверить статус
sudo systemctl status openvpn-collector
sudo systemctl status openvpn-web
sudo systemctl list-timers openvpn-sync.timer

# Просмотр логов
sudo journalctl -u openvpn-collector -f
sudo journalctl -u openvpn-web -f
```

## Мониторинг

### Health Check

```bash
# Проверка web приложения
curl -u admin:password http://localhost:8000/api/v1/stats/overview

# Проверка БД
mysql -u ovpn_collector -p -e "SELECT 1 FROM accounts LIMIT 1;" openvpn_logs
```

### Метрики (опционально)

```python
# Добавить endpoint для Prometheus
@app.get("/metrics")
async def metrics():
    return {
        "active_sessions": await get_active_session_count(),
        "total_accounts": await get_total_account_count(),
        "failed_attempts_24h": await get_failed_attempts_count(hours=24)
    }
```

## Backup

```bash
#!/bin/bash
# /opt/openvpn-logserver/scripts/backup.sh

BACKUP_DIR="/backup/openvpn-logserver"
DATE=$(date +%Y%m%d_%H%M%S)

# Backup database
mysqldump -u root -p openvpn_logs > "$BACKUP_DIR/db_$DATE.sql"

# Backup config
cp -r /etc/openvpn-logserver "$BACKUP_DIR/config_$DATE"

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
sudo systemctl stop openvpn-collector openvpn-web

# Update code
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r collector/requirements.txt --upgrade
pip install -r web/requirements.txt --upgrade

# Run migrations
alembic upgrade head

# Start services
sudo systemctl start openvpn-collector openvpn-web

# Check status
sudo systemctl status openvpn-collector openvpn-web
```
