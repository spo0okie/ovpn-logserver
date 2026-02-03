# Модуль сбора данных (Python Collector)

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Collector                           │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Connect    │  │  Disconnect  │  │  Auth Failed │      │
│  │   Script     │  │   Script     │  │   Script     │      │
│  │  (Python)    │  │   (Python)   │  │   (Python)   │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         └──────────────────┼──────────────────┘             │
│                            │                                │
│                            ▼                                │
│              ┌─────────────────────────┐                   │
│              │    Direct MySQL Write   │                   │
│              │   (with error handling) │                   │
│              └─────────────────────────┘                   │
│                            │                                │
│                            ▼                                │
│                      ┌──────────┐                          │
│                      │  MySQL   │                          │
│                      └──────────┘                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           Background Sync Tasks (cron)              │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │   │
│  │  │  cert_sync   │ │ crl_checker  │ │  ccd_checker │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Компоненты

### 1. client-connect Script

Вызывается OpenVPN при подключении клиента.

**OpenVPN передает переменные окружения:**
- `common_name` - CN сертификата
- `trusted_ip` - IP клиента
- `trusted_port` - порт клиента
- `ifconfig_pool_remote_ip` - выделенный VPN IP
- `time_unix` - timestamp подключения

**Алгоритм работы:**
1. Получает переменные окружения от OpenVPN
2. Запрашивает геолокацию IP (с кэшированием)
3. Создает или обновляет запись в `accounts`
4. Создает запись в `sessions` со статусом 'active'
5. Возвращает exit code 0 (успех) или 1 (ошибка)

**Код wrapper-скрипта:**

Создайте файл `/etc/openvpn/scripts/client-connect`:

```python
#!/usr/bin/env python3
"""
Wrapper для client-connect скрипта OpenVPN.
"""
import sys

# Добавляем путь к проекту для импорта модулей
sys.path.insert(0, '/opt/openvpn-logserver')

from collector.client_connect import main

if __name__ == '__main__':
    sys.exit(main())
```

Основная логика находится в [`collector/client_connect.py`](collector/client_connect.py):

```python
import os
import sys
import logging
from datetime import datetime

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import Account, Session
from core.geoip import resolve_geoip

def main():
    # Получаем переменные от OpenVPN
    cn = os.environ.get('common_name')
    source_ip = os.environ.get('trusted_ip')
    virtual_ip = os.environ.get('ifconfig_pool_remote_ip')
    
    if not cn or not source_ip:
        logging.warning("Missing required environment variables")
        return 0  # Не блокируем VPN
    
    db = SessionLocal()
    try:
        # Создаем или получаем account (upsert без SELECT)
        account = Account(cn=cn)
        merged_account = db.merge(account)
        db.flush()
        
        # Получаем геолокацию
        geo = resolve_geoip(source_ip, db)
        
        # Создаем сессию
        session = Session(
            account_id=merged_account.id,
            connected_at=datetime.utcnow(),
            source_ip=source_ip,
            country=geo.get('country') if geo else None,
            city=geo.get('city') if geo else None,
            virtual_ip=virtual_ip,
            status='active'
        )
        db.add(session)
        db.commit()
        
        return 0
        
    except Exception as e:
        logging.error(f"Error: {e}")
        return 0  # Не блокируем VPN при ошибке
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())
```

### 2. client-disconnect Script

Вызывается OpenVPN при отключении клиента.

**OpenVPN передает переменные:**
- `common_name` - CN сертификата
- `time_duration` - длительность сессии в секундах
- `bytes_sent` - отправлено байт
- `bytes_received` - получено байт

**Алгоритм:**
1. Получает переменные окружения
2. Находит активную сессию по CN
3. Обновляет `disconnected_at`, `status='closed'`, трафик
4. Возвращает exit code 0

**Код wrapper-скрипта:**

Создайте файл `/etc/openvpn/scripts/client-disconnect`:

```python
#!/usr/bin/env python3
"""
Wrapper для client-disconnect скрипта OpenVPN.
"""
import sys

# Добавляем путь к проекту для импорта модулей
sys.path.insert(0, '/opt/openvpn-logserver')

from collector.client_disconnect import main

if __name__ == '__main__':
    sys.exit(main())
```

Основная логика находится в [`collector/client_disconnect.py`](collector/client_disconnect.py):

```python
import os
import sys
import logging
from datetime import datetime

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import Account, Session

def main():
    cn = os.environ.get('common_name')
    bytes_sent = int(os.environ.get('bytes_sent', 0))
    bytes_received = int(os.environ.get('bytes_received', 0))
    
    if not cn:
        return 0  # Не критичная ошибка
    
    db = SessionLocal()
    try:
        # Находим последнюю активную сессию по CN
        active_session = db.query(Session).join(Account).filter(
            Account.cn == cn,
            Session.status == 'active'
        ).order_by(Session.connected_at.desc()).first()
        
        if active_session:
            active_session.disconnected_at = datetime.utcnow()
            active_session.status = 'closed'
            active_session.bytes_sent = bytes_sent
            active_session.bytes_received = bytes_received
            db.commit()
        
        return 0
        
    except Exception as e:
        logging.error(f"Error: {e}")
        return 0  # Не блокируем отключение
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())
```

### 3. auth-failed Script (опционально)

Для фиксации неудачных попыток можно использовать `tls-verify` скрипт или парсить логи.

**Вариант 1 - через tls-verify (не рекомендуется):**
- Сложно отличить разные типы ошибок
- Блокирует процесс подключения

**Вариант 2 - через логи (рекомендуется):**
- Простой скрипт на Python читает syslog
- Фильтрует ошибки аутентификации
- Пишет в `connection_attempts`

**Простой log watcher для ошибок:**
```python
#!/opt/openvpn-logserver/venv/bin/python
# /opt/openvpn-logserver/collector/error_watcher.py

import sys
import MySQLdb
import re

def parse_log_line(line):
    # Паттерны ошибок
    patterns = [
        (r'CRL check failed:.*?CN=(\S+)', 'cert_revoked'),
        (r'VERIFY ERROR:.*?CN=(\S+)', 'verify_error'),
        (r'Could not access config file:.*ccd/(\S+)', 'ccd_missing'),
    ]
    
    for pattern, failure_type in patterns:
        match = re.search(pattern, line)
        if match:
            return {
                'cn': match.group(1),
                'type': failure_type,
                'line': line
            }
    return None

def main():
    # Читаем stdin (данные от journald или файл)
    for line in sys.stdin:
        error = parse_log_line(line)
        if error:
            # Пишем в БД
            pass

if __name__ == '__main__':
    main()
```

### 4. geoip_resolver.py

Модуль для определения геолокации с кэшированием.

```python
# /opt/openvpn-logserver/collector/geoip_resolver.py

import requests
import MySQLdb
from datetime import datetime, timedelta

def resolve_geoip(ip: str) -> dict:
    """Получает геолокацию IP с кэшированием"""
    
    # Проверяем кэш
    db = MySQLdb.connect(host="localhost", user="ovpn_collector", db="openvpn_logs")
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    
    cursor.execute(
        "SELECT * FROM geoip_cache WHERE ip = %s AND expires_at > NOW()",
        (ip,)
    )
    cached = cursor.fetchone()
    
    if cached:
        cursor.close()
        db.close()
        return {
            'country': cached['country'],
            'city': cached['city'],
            'country_code': cached['country_code']
        }
    
    # Запрашиваем внешний API
    try:
        response = requests.get(f'http://ip-api.com/json/{ip}', timeout=5)
        data = response.json()
        
        if data.get('status') == 'success':
            # Сохраняем в кэш
            cursor.execute("""
                INSERT INTO geoip_cache (ip, country, country_code, city, cached_at, expires_at)
                VALUES (%s, %s, %s, %s, NOW(), DATE_ADD(NOW(), INTERVAL 7 DAY))
                ON DUPLICATE KEY UPDATE
                    country = VALUES(country),
                    city = VALUES(city),
                    cached_at = VALUES(cached_at),
                    expires_at = VALUES(expires_at)
            """, (ip, data.get('country'), data.get('countryCode'), data.get('city')))
            db.commit()
            
            return {
                'country': data.get('country'),
                'city': data.get('city'),
                'country_code': data.get('countryCode')
            }
    except Exception as e:
        print(f"GeoIP error: {e}")
    
    cursor.close()
    db.close()
    return {'country': None, 'city': None, 'country_code': None}
```

### 5. Фоновые задачи (cron)

Остаются для синхронизации сертификатов, CRL, CCD:

- **cert_sync.py** - создание accounts из неотозванных сертификатов и обновление сроков
- **crl_checker.py** - проверка отозванных сертификатов
- **ccd_checker.py** - проверка наличия CCD файлов

#### cert_sync.py

Сканирует директорию с сертификатами и синхронизирует с БД:

1. **Парсит CRL** для определения отозванных сертификатов
2. **Для каждого неотозванного сертификата**:
   - Создаёт account если CN не существует (INSERT через `db.merge()`)
   - Обновляет `valid_from` и `valid_to` из сертификата
3. **Отозванные сертификаты пропускаются** — для них account не создаётся

**Инварианты:**
- I6.1: Обновляет `valid_from`, `valid_to` из сертификатов
- I6.4: Идемпотентен (повторный запуск не ломает данные)
- I6.5: Создаёт accounts для неотозванных CN (INSERT или UPDATE через `merge()`)

**Пример работы:**
```python
# Сканируем /etc/openvpn/certs
# Находим: client1.crt (не отозван), client2.crt (отозван в CRL)
# Результат:
# - client1: создан или обновлён в БД
# - client2: пропущен (не создаём account для отозванного)
```

## Преимущества подхода со скриптами

1. **Надежность** - события фиксируются синхронно с подключением
2. **Проще** - нет необходимости в демоне, читающем логи
3. **Точность** - нет задержек, данные актуальны
4. **Производительность** - скрипты выполняются быстро (< 100ms)

## Недостатки и решения

| Недостаток | Решение |
|------------|---------|
| Задержка подключения при медленной БД | Connection pool, быстрый INSERT |
| Скрипт может упасть | try/except, exit 0 при ошибках |
| Нет данных о неудачных попытках | Отдельный watcher для логов ошибок |
| Нужен Python на сервере | Уже есть для коллектора |

## Конфигурация OpenVPN

```conf
# client-connect script
client-connect /etc/openvpn/scripts/client-connect

# client-disconnect script
client-disconnect /etc/openvpn/scripts/client-disconnect

# Для ошибок используем логи
log-append /var/log/openvpn/server.log
verb 3
```

## Права доступа

```bash
# Создаем директорию для скриптов
mkdir -p /etc/openvpn/scripts
chown root:ovpn-logserver /etc/openvpn/scripts
chmod 750 /etc/openvpn/scripts

# Создаем wrapper-скрипты (не копируем Python файлы напрямую!)
# См. примеры в collector/openvpn_scripts/
cat > /etc/openvpn/scripts/client-connect <<'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/openvpn-logserver')
from collector.client_connect import main
if __name__ == '__main__':
    sys.exit(main())
EOF

cat > /etc/openvpn/scripts/client-disconnect <<'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/openvpn-logserver')
from collector.client_disconnect import main
if __name__ == '__main__':
    sys.exit(main())
EOF

# Скрипты должны быть executable
chmod 755 /etc/openvpn/scripts/client-connect
chmod 755 /etc/openvpn/scripts/client-disconnect

# Права на запись в БД для ovpn_collector
# (настраивается в MySQL)
```
