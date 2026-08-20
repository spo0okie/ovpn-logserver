# Требования к конфигурации OpenVPN

Без перечисленного ниже collector **молча не собирает данные** — сервер при этом
работает нормально, и понять, что журнал пуст «не просто так», трудно.

## Обязательный минимум в `server.conf`

```
# Без этого OpenVPN 2.6 просто не исполняет внешние скрипты,
# и ни одна сессия не попадёт в БД
script-security 2

client-connect    /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# Нужен для обнаружения оборванных сессий (session_cleanup)
management /run/openvpn/mgmt.sock unix

# Источники данных для периодических синков
client-config-dir /etc/openvpn/ccd
crl-verify        /etc/openvpn/crl.pem
```

Требуется OpenVPN 2.5+.

### Почему именно так

- **`script-security 2`** — самый частый источник «ничего не работает, ошибок нет».
- **`management ... unix`** — `collector/mgmt_client.py` умеет только unix-сокет,
  TCP-вариант не поддерживается. Путь к сокету настраивается
  (`OPENVPN_MGMT_SOCKET` → `config/openvpn.yaml: management_socket` → дефолт
  `/var/run/openvpn/mgmt.sock`) и должен совпадать с указанным в `server.conf`.
- **`setenv-safe` использовать не нужно**: директива добавляет к имени префикс
  `OPENVPN_` (`setenv-safe CERTS_DIR` → переменная `OPENVPN_CERTS_DIR`), поэтому
  скрипты, читающие `CERTS_DIR`, значения не увидят. Пути передаются через
  окружение процесса OpenVPN.

## Переменные окружения, которые читают хуки

`client-connect`: `common_name`, `trusted_ip`, `trusted_port`,
`ifconfig_pool_remote_ip`, `time_unix`, **`tls_serial_0`**.

`client-disconnect`: те же плюс `bytes_sent`, `bytes_received`, `time_duration`.

⚠️ Именно `tls_serial_0`, а не `tls_serial`: без него не работает учёт нескольких
сертификатов на пользователя.

## Пути к данным

Настраиваются через `config/openvpn.yaml` или ENV (`OPENVPN_DIR`, `CERTS_DIR`,
`CRL_FILE`, `CCD_DIR`):

| Что | Кто читает | Требование |
|---|---|---|
| каталог сертификатов | `cert_sync` | **плоский** список файлов, вложенные каталоги не обходятся |
| файл CRL | `crl_checker` | тот же путь, что в `crl-verify` |
| каталог CCD | `ccd_checker` | имя файла = CN **целиком** (точка в CN не обрезается) |

⚠️ `cert_sync` ищет файлы по маске `*<cert_extension>` (по умолчанию `.crt`)
непосредственно в каталоге сертификатов. Если сертификаты разложены по подкаталогам
вида `clients/<CN>/<CN>.crt`, синк не найдёт ничего и молча отработает вхолостую:
даты сертификатов останутся пустыми. Типичная альтернатива — указать каталог CA
`newcerts` (там файлы названы по серийнику) и `cert_extension: .pem`.

Начиная с текущей версии такая ситуация логируется явно: при нулевом результате
`cert_sync` сообщает, файлов какого расширения он не нашёл и какие расширения в
каталоге есть на самом деле.

## Проверка

```bash
# Хуки исполняются и не блокируют VPN
python3 /etc/openvpn/scripts/client-connect; echo "exit=$?"   # должно быть 0

# Management-сокет доступен
ls -l /run/openvpn/mgmt.sock

# Что видит cert_sync
python3 -c "from collector.cert_sync import find_cert_files; \
from collector.config import CERTS_DIR; print(len(find_cert_files(CERTS_DIR)))"
```

Хуки исполняются под тем пользователем, под которым работает OpenVPN (часто
`nobody` после сброса привилегий) — конфиг с паролем БД должен быть ему доступен
на чтение, иначе подключение к БД не состоится. Сами хуки при этом всё равно
вернут 0 и не заблокируют VPN (инвариант I4.5), но данные записаны не будут.
