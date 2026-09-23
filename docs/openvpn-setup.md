# Требования к конфигурации OpenVPN

Без перечисленного ниже collector **молча не собирает данные** — сервер при этом
работает нормально, и понять, что журнал пуст «не просто так», трудно.

## Обязательный минимум в `server.conf`

```
# Без этого OpenVPN не исполняет внешние скрипты,
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

Требуется OpenVPN 2.5+. Обёртки `client-connect`/`client-disconnect` берутся
из репозитория — как их ставить и почему не писать вручную,
[collector/openvpn_scripts/README.md](../collector/openvpn_scripts/README.md).

Мультисайт: каждому инстансу нужно ещё своё имя —
`setenv OPENVPN_SERVER_NAME <имя>` в его server.conf, см. [multisite.md](multisite.md).

### Почему именно так

- **`script-security 2`** — самый частый источник «ничего не работает, ошибок нет».
- **`management ... unix`** — `collector/mgmt_client.py` умеет только unix-сокет,
  TCP-вариант не поддерживается. Путь к сокету настраивается
  (`OPENVPN_MGMT_SOCKET` → `config/openvpn.yaml: management_socket` → дефолт
  `/var/run/openvpn/mgmt.sock`) и должен совпадать с указанным в `server.conf`.
  На Debian `/var/run` — ссылка на `/run`, так что `/run/openvpn/mgmt.sock` в
  server.conf и дефолт — один и тот же файл.
- **Свои переменные для хуков — через `setenv`, а не `setenv-safe`.**
  `setenv-safe NAME` добавляет к имени префикс `OPENVPN_`, и хук ищет
  переменную не под тем именем. Хукам из «своих» переменных нужны только
  `OPENVPN_SERVER_NAME` (мультисайт) и, при нестандартном пути проекта,
  `OPENVPN_LOGSERVER_PATH`. Пути к PKI и CCD хуки не читают вовсе. Переменные
  клиента (ниже) OpenVPN передаёт сам — объявлять их не нужно.

## Переменные окружения, которые читают хуки

`client-connect`: `common_name`, `trusted_ip`, `trusted_port`,
`ifconfig_pool_remote_ip`, `time_unix`, **`tls_serial_0`**.

`client-disconnect`: `common_name`, `bytes_sent`, `bytes_received`,
`time_duration`.

⚠️ Именно `tls_serial_0`, а не `tls_serial`: без него не работает учёт нескольких
сертификатов на пользователя.

## Пути к данным

Задаются в `config/openvpn.yaml` или ENV `OPENVPN_CERTS_DIR`,
`OPENVPN_CERT_EXTENSION`, `OPENVPN_CRL_FILE`, `OPENVPN_CCD_DIR` (ключи, дефолты,
устаревшие алиасы — [config/README.md](../config/README.md)):

| Что | Кто читает | Требование |
|---|---|---|
| каталог сертификатов | `cert_sync` | **плоский** список файлов, вложенные каталоги не обходятся |
| файл CRL | `crl_checker` | тот же путь, что в `crl-verify` |
| каталог CCD | `ccd_checker` | тот же путь, что в `client-config-dir`; имя файла = CN **целиком** (точка в CN не обрезается) |

⚠️ `cert_sync` ищет файлы по маске `*<cert_extension>` (по умолчанию `.crt`)
непосредственно в каталоге сертификатов. Если сертификаты разложены по подкаталогам
вида `clients/<CN>/<CN>.crt`, синк не найдёт ничего и молча отработает вхолостую:
даты сертификатов останутся пустыми. Типичная альтернатива — указать каталог CA
`newcerts` (там файлы названы по серийнику) и `cert_extension: .pem`.
Такая ситуация логируется явно: при нулевом результате `cert_sync` сообщает,
файлов какого расширения он не нашёл и какие расширения в каталоге есть.

⚠️ Несуществующий CCD-каталог (опечатка в пути) `ccd_checker` не считает
«CCD нет ни у кого»: статусы CCD этого сервера остаются как были, в
`ccd-checker.log` пишется предупреждение. Существующий пустой каталог — это
законное «CCD нет».

## Проверка

```bash
# Хуки исполняются и не блокируют VPN. Запускать сам файл, а не через python3:
# так проверяется и шебанг (при установке в venv он указывает на venv/bin/python)
/etc/openvpn/scripts/client-connect; echo "exit=$?"   # должно быть 0

# Management-сокет доступен
ls -l /run/openvpn/mgmt.sock

# Что видит cert_sync (из каталога проекта; venv/bin/python — при установке
# в venv, иначе python3)
cd /opt/openvpn-logserver && venv/bin/python -c "from collector.cert_sync import find_cert_files; \
from collector.config import CERTS_DIR; print(len(find_cert_files(CERTS_DIR)))"
```

Хуки исполняются под тем пользователем, под которым работает OpenVPN (часто
`nobody` после сброса привилегий) — конфиг с паролем БД должен быть ему доступен
на чтение, иначе подключение к БД не состоится. Сами хуки при этом всё равно
вернут 0 и не заблокируют VPN (инвариант I4.5), но данные записаны не будут.
