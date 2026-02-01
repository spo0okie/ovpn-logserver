# Конфигурация OpenVPN

## Требования к OpenVPN

- Версия: 2.5+
- ОС: Debian/Ubuntu Linux
- Права: root или sudo для настройки

## Необходимые настройки

### 1. Client Connect/Disconnect Scripts

Добавить в `/etc/openvpn/server.conf`:

```conf
# Скрипт, вызываемый при подключении клиента
client-connect /etc/openvpn/scripts/client-connect

# Скрипт, вызываемый при отключении клиента
client-disconnect /etc/openvpn/scripts/client-disconnect

# Таймаут выполнения скриптов (в секундах)
script-security 2
```

### 2. Логирование (для ошибок)

```conf
# Лог-файл для отслеживания ошибок аутентификации
log-append /var/log/openvpn/server.log

# Уровень детализации логов
verb 3
```

### 3. Client Config Directory (CCD)

```conf
# Директория с индивидуальными настройками клиентов
client-config-dir /etc/openvpn/ccd

# Требовать наличие CCD файла для подключения (опционально)
;ccd-exclusive
```

### 4. CRL (Certificate Revocation List)

```conf
# Файл со списком отозванных сертификатов
crl-verify /etc/openvpn/crl.pem
```

### 5. Переменные окружения для скриптов

OpenVPN передает скриптам следующие переменные:

**client-connect:**
- `common_name` - CN из сертификата
- `trusted_ip` - IP адрес клиента
- `trusted_port` - порт клиента
- `ifconfig_pool_remote_ip` - выделенный VPN IP
- `time_unix` - timestamp подключения
- `tls_serial` - серийный номер сертификата

**client-disconnect:**
- `common_name` - CN из сертификата
- `trusted_ip` - IP адрес клиента
- `bytes_sent` - байт отправлено
- `bytes_received` - байт получено
- `time_duration` - длительность сессии в секундах
- `time_unix` - timestamp отключения

Полный список: https://openvpn.net/community-resources/reference-manual-for-openvpn-2-6/

### 5. Структура директорий клиентов

Рекомендуемая структура:

```
/etc/openvpn/
├── server.conf
├── ca.crt
├── crl.pem
├── clients/                    # Директория с сертификатами
│   ├── org_user1/
│   │   ├── client.crt
│   │   ├── client.key
│   │   └── ca.crt
│   ├── org_user2/
│   │   └── ...
│   └── org_user3/
│       └── ...
└── ccd/                        # Client Config Directory
    ├── user1                   # Файл с именем = CN
    ├── user2
    └── user3
```

## Права доступа

```bash
# Создать пользователя для коллектора
useradd -r -s /bin/false ovpn-collector

# Права на лог-файлы
chown root:ovpn-collector /var/log/openvpn/server.log
chmod 640 /var/log/openvpn/server.log

# Права на директорию clients (только чтение)
chown -R root:ovpn-collector /etc/openvpn/clients
chmod -R 750 /etc/openvpn/clients

# Права на CCD (только чтение)
chown -R root:ovpn-collector /etc/openvpn/ccd
chmod -R 750 /etc/openvpn/ccd

# Права на CRL (только чтение)
chown root:ovpn-collector /etc/openvpn/crl.pem
chmod 640 /etc/openvpn/crl.pem
```

## Примеры логов OpenVPN

### Успешное подключение

```
2024-01-31 10:00:00 us=123456 1.2.3.4:54321 TLS: Initial packet from [AF_INET]1.2.3.4:54321, sid=abc123
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 VERIFY OK: depth=1, CN=OpenVPN CA
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 VERIFY OK: depth=0, CN=user1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_VER=2.5.0
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_PLAT=linux
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_PROTO=2
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_NCP=2
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_CIPHERS=AES-256-GCM:AES-128-GCM
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_LZ4=1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_LZ4v2=1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_LZO=1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_COMP_STUB=1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_COMP_STUBv2=1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_TCPNL=1
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_GUI_VER="OpenVPN GUI 11.0.0.0"
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 peer info: IV_SSO=openurl,crtext
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 Control Channel: TLSv1.3, cipher TLSv1.3 TLS_AES_256_GCM_SHA384, peer certificate: 256 bit EC, curve prime256v1, signature: ecdsa-with-SHA256
2024-01-31 10:00:01 us=234567 1.2.3.4:54321 [user1] Peer Connection Initiated with [AF_INET]1.2.3.4:54321
2024-01-31 10:00:01 us=234567 user1/1.2.3.4:54321 OPTIONS IMPORT: reading client specific options from: /etc/openvpn/ccd/user1
2024-01-31 10:00:01 us=234567 user1/1.2.3.4:54321 MULTI: Learn: 10.8.0.5 -> user1/1.2.3.4:54321
2024-01-31 10:00:01 us=234567 user1/1.2.3.4:54321 MULTI: primary virtual IP for user1/1.2.3.4:54321: 10.8.0.5
2024-01-31 10:00:02 us=345678 user1/1.2.3.4:54321 PUSH: Received control message: 'PUSH_REQUEST'
2024-01-31 10:00:02 us=345678 user1/1.2.3.4:54321 SENT CONTROL [user1]: 'PUSH_REPLY,redirect-gateway def1 bypass-dhcp,dhcp-option DNS 8.8.8.8,route-gateway 10.8.0.1,topology subnet,ping 10,ping-restart 120,ifconfig 10.8.0.5 255.255.255.0,peer-id 0,cipher AES-256-GCM' (status=1)
```

### Отключение клиента

```
2024-01-31 12:30:00 us=456789 user1/1.2.3.4:54321 Connection reset, restarting [0]
2024-01-31 12:30:00 us=456789 user1/1.2.3.4:54321 SIGUSR1[soft,connection-reset] received, client-instance restarting
2024-01-31 12:30:00 us=456789 user1/1.2.3.4:54321 Restart pause, 1 second(s)
```

Или:

```
2024-01-31 12:30:00 us=456789 user1/1.2.3.4:54321 client-instance exiting
```

### Отозванный сертификат

```
2024-01-31 10:05:00 us=567890 5.6.7.8:12345 VERIFY ERROR: depth=0, error=CRL has expired: CN=user2, serial=9876543210
2024-01-31 10:05:00 us=567890 5.6.7.8:12345 OpenSSL: error:14089086:SSL routines:ssl3_get_client_certificate:certificate verify failed
2024-01-31 10:05:00 us=567890 5.6.7.8:12345 TLS_ERROR: BIO read tls_read_plaintext error
2024-01-31 10:05:00 us=567890 5.6.7.8:12345 TLS Error: TLS object -> incoming plaintext read error
2024-01-31 10:05:00 us=567890 5.6.7.8:12345 TLS Error: TLS handshake failed
```

### Отсутствие CCD файла

```
2024-01-31 10:10:00 us=678901 9.8.7.6:45678 [user3] Peer Connection Initiated with [AF_INET]9.8.7.6:45678
2024-01-31 10:10:00 us=678901 user3/9.8.7.6:45678 OPTIONS IMPORT: reading client specific options from: /etc/openvpn/ccd/user3
2024-01-31 10:10:00 us=678901 user3/9.8.7.6:45678 Could not access config file: /etc/openvpn/ccd/user3
2024-01-31 10:10:00 us=678901 user3/9.8.7.6:45678 Connection reset, restarting [-1]
```

### Ошибка TLS

```
2024-01-31 10:15:00 us=789012 1.1.1.1:99999 TLS Error: incoming packet authentication failed from [AF_INET]1.1.1.1:99999
```

## Паттерны для парсинга

```python
# Подключение клиента
CONNECT_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?'
    r'(\d+\.\d+\.\d+\.\d+):(\d+).*?'
    r'\[([^\]]+)\] Peer Connection Initiated',
    re.MULTILINE
)

# Отключение клиента
DISCONNECT_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?'
    r'([^/]+)/(\d+\.\d+\.\d+\.\d+):(\d+).*?'
    r'(?:client-instance exiting|Connection reset)',
    re.MULTILINE
)

# Получение виртуального IP
VIRTUAL_IP_PATTERN = re.compile(
    r'primary virtual IP for .+: (\d+\.\d+\.\d+\.\d+)'
)

# Ошибка верификации
VERIFY_ERROR_PATTERN = re.compile(
    r'VERIFY ERROR:.*?CN=([^,]+)'
)

# Отозванный сертификат
REVOKED_PATTERN = re.compile(
    r'CRL has expired: CN=([^,]+)'
)

# Отсутствие CCD
CCD_MISSING_PATTERN = re.compile(
    r'Could not access config file: .+/ccd/(.+)$'
)
```

## Проверка конфигурации

```bash
# Проверить конфигурацию OpenVPN
openvpn --config /etc/openvpn/server.conf --verb 3 --dev null

# Проверить доступность management interface
echo "status" | nc localhost 7505

# Проверить права на лог-файл
ls -la /var/log/openvpn/

# Проверить структуру clients
find /etc/openvpn/clients -name "*.crt" | head -5

# Проверить CCD файлы
ls -la /etc/openvpn/ccd/

# Проверить CRL
openssl crl -in /etc/openvpn/crl.pem -text -noout | head -20
```
