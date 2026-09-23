# Развертывание и Systemd сервисы

Этот документ описывает **single-site**: web, MySQL и сборщик на одном хосте с
OpenVPN. Для нескольких OpenVPN-серверов с центральным CA — [multisite.md](multisite.md);
разделы ниже там переиспользуются по ролям хостов:

| Хост | Что из этого документа | Отличия в мультисайте |
|---|---|---|
| админ-хост (CA) | MySQL, миграции, web, `openvpn-sync.service` | синк в роли `central` (`SYNC_ROLE=central`); разделы про OpenVPN не нужны |
| сервер сайта | подключение хуков к OpenVPN | web и MySQL не ставятся; синк — шаблонный `openvpn-sync-site@.service` |

⚠️ На админ-хосте штатный `openvpn-sync.service` без переопределения роли
запускает `all`: ccd_checker и session_cleanup отработают вхолостую и
зарегистрируют в `vpn_servers` фантомный сервер `local`. Как задать роль —
[multisite.md](multisite.md#админ-хост-ca).

Обновление существующей установки на версию с мультисайтом (миграция 005,
`server_name`) — [multisite.md](multisite.md#миграция-существующей-single-site-установки).

## Быстрый старт для root

Минимальная установка для работы под пользователем root.

### Требования
- Debian/Ubuntu
- Python 3.10+
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
cp config/openvpn.yaml.example  config/openvpn.yaml

# Создание директории для логов
mkdir -p /opt/openvpn-logserver/logs
```

### 2. Подключение скриптов к OpenVPN

Скрипты `client-connect` и `client-disconnect` фиксируют подключения в БД.

#### 2.1 Обёртки хуков

OpenVPN вызывает не сами `collector/client_connect.py`/`client_disconnect.py`,
а обёртки из `collector/openvpn_scripts/`: они добавляют проект в `sys.path` и
перехватывают **любой** сбой импорта с exit 0. Без этого ошибка конфига или
недостающая зависимость дадут ненулевой код, и OpenVPN откажет клиенту в
подключении (инвариант I4.5). Поэтому обёртки копируются из репозитория, а не
пишутся вручную.

```bash
mkdir -p /etc/openvpn/scripts
cp collector/openvpn_scripts/client-connect collector/openvpn_scripts/client-disconnect /etc/openvpn/scripts/
chmod 755 /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
```

Путь к проекту обёртки берут из ENV `OPENVPN_LOGSERVER_PATH` (по умолчанию
`/opt/openvpn-logserver`). Шебанг — `#!/usr/bin/env python3`, то есть системный
Python: подходит для этой установки, где зависимости ставились глобально. Для
установки с venv шебанг меняется — см. шаг 6 раздела с изоляцией.

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

Хуки выполняются от пользователя процесса OpenVPN. Если в server.conf есть
сброс привилегий (`user nobody`), этому пользователю нужно право читать
`config/database.yaml` — иначе хук не подключится к БД: VPN продолжит работать
(fail-open), но сессии молча перестанут записываться. Ошибка будет видна в
`client-connect.log` (каталог `/var/log/openvpn-logserver/`, а если его нет —
`logs/` в каталоге проекта).

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

Отредактируйте `config/openvpn.yaml` — откуда синк читает данные и как
называется этот сервер:
- `certs_dir` + `cert_extension` — выпущенные сертификаты (у provision:
  `/etc/openvpn/certs`, расширение `.pem`, имя файла = серийник);
- `crl_file` — CRL (у provision: `/etc/openvpn/clients/revoked.crl`);
- `ccd_dir` и `management_socket` — должны совпадать с `client-config-dir` и
  `management` в server.conf;
- `server_name` — имя сервера в журнале сессий (любое осмысленное, дефолт
  `local`).

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
│   ├── openvpn.yaml             # Пути PKI/CCD, mgmt-сокет, имя сервера
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

# Пути PKI/CCD, mgmt-сокет и имя сервера: скопировать образец и
# отредактировать — ключи описаны в «3. Настройка конфигурации»
sudo cp /opt/openvpn-logserver/config/openvpn.yaml.example /opt/openvpn-logserver/config/openvpn.yaml

# Конфигурация web-приложения. Код читает только app.debug и cors.*
# (web/main.py); хост, порт и число воркеров задаются в openvpn-web.service
sudo tee /opt/openvpn-logserver/config/web.yaml <<EOF
app:
  debug: false        # true открывает /docs и /openapi.json — не для прода

cors:
  allow_origins: []   # ["*"] вместе с credentials небезопасен — CORS отключится
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

#### 6. Подключение обёрток хуков

Обёртки копируются из репозитория (почему не вручную — см. «2.1 Обёртки
хуков»). Зависимости в этой установке стоят в venv, поэтому шебанг
переключается на его интерпретатор:

```bash
sudo mkdir -p /etc/openvpn/scripts
sudo cp collector/openvpn_scripts/client-connect collector/openvpn_scripts/client-disconnect /etc/openvpn/scripts/
sudo sed -i '1s|.*|#!/opt/openvpn-logserver/venv/bin/python|' /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
sudo chmod 755 /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
```

Хуки выполняются от пользователя процесса OpenVPN, а конфиги здесь закрыты
правами `640 ovpn-logserver` (шаг 4). Если OpenVPN работает от root — всё в
порядке. Если в server.conf есть `user nobody`, хук не прочитает
`config/database.yaml`, и сессии молча перестанут записываться (VPN продолжит
работать — fail-open). Тогда добавьте пользователя OpenVPN в группу
`ovpn-logserver` или ослабьте права на `database.yaml`.

#### 7. Настройка OpenVPN

Добавьте в конфигурацию OpenVPN (`/etc/openvpn/server.conf`):

```conf
# Без script-security 2 хуки не исполняются — сессии молча не пишутся
script-security 2

client-connect /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# Нужен session_cleanup для обнаружения оборванных сессий
management /run/openvpn/mgmt.sock unix
```

Путь сокета должен совпадать с `management_socket` в `config/openvpn.yaml`, а
пользователь синка (`ovpn-logserver`) — иметь право к нему подключаться.
Иначе session_cleanup по fail-closed-правилу (C1.7) будет на каждом запуске
пропускать очистку — это видно в `session-cleanup.log`. Полный список
требований — [openvpn-setup.md](openvpn-setup.md).

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
Documentation=https://github.com/spo0okie/ovpn-logserver
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

Периодическая синхронизация — `collector/sync_all.py`: сертификаты, CRL, CCD и
закрытие оборванных сессий, строго в этом порядке и с защитой от параллельного
запуска. Вызывать функции синка из юнита по отдельности нельзя: так теряются
`session_cleanup`, lock и правило «очистка только после успешного синка» (S3.2).

```bash
# Timer
sudo tee /etc/systemd/system/openvpn-sync.timer <<'EOF'
[Unit]
Description=OpenVPN Data Sync Timer
Documentation=https://github.com/spo0okie/ovpn-logserver

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
Documentation=https://github.com/spo0okie/ovpn-logserver
After=mysql.service

[Service]
Type=oneshot
User=ovpn-logserver
Group=ovpn-logserver
WorkingDirectory=/opt/openvpn-logserver

# Роль синка: all — single-site. На админ-хосте мультисайта — central
# (см. docs/multisite.md)
Environment=SYNC_ROLE=all

ExecStart=/opt/openvpn-logserver/venv/bin/python /opt/openvpn-logserver/collector/sync_all.py

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/opt/openvpn-logserver/config
ReadOnlyPaths=/etc/openvpn
# При ProtectSystem=strict файловая система read-only. Без этих двух строк не
# создадутся lock-файл (/run/openvpn-logserver) и логи синка
# (/var/log/openvpn-logserver): синк шёл бы без блокировки и писал только в
# журнал systemd
RuntimeDirectory=openvpn-logserver
LogsDirectory=openvpn-logserver
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
sudo -u ovpn-logserver git pull

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

При переходе на версию с мультисайтом (миграция 005) после обновления нужно
задать `server_name` и при желании перенести старые сессии на этот сервер —
[multisite.md](multisite.md#миграция-существующей-single-site-установки).

## Порядок развертывания (кратко)

1. **Установить зависимости** — Python, MySQL, Git
2. **Создать `config/*.yaml`** — `database.yaml` (подключение к БД), `auth.yaml`
   (учётные данные UI), `openvpn.yaml` (пути PKI/CCD, mgmt-сокет, `server_name`)
3. **Применить миграции** — `cd database && alembic upgrade head`
4. **Подключить хуки к OpenVPN** — скопировать обёртки из
   `collector/openvpn_scripts/`; в server.conf — `script-security 2`,
   `client-connect`, `client-disconnect`, `management`
5. **Запустить компоненты** — web и таймер синхронизации

Мультисайт — тот же набор, разнесённый по ролям хостов: [multisite.md](multisite.md).
