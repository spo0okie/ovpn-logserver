# Конфигурация

Единая точка загрузки — `core/config.py`: YAML из этого каталога плюс
переопределение переменными окружения поверх. **ENV всегда приоритетнее YAML.**
Все YAML-файлы необязательны: любой набор значений можно задать только через
ENV. Захардкоженных паролей нет — при отсутствии обязательного значения
приложение падает с `ConfigError`, например `Database config: 'password' is empty`.

Файлы создаются из образцов `*.yaml.example` и в git не коммитятся. Комментарии
в образцах — основная справка по ключам; ниже только сводка и то, чего в
образцах нет.

`core/config.py` читает **только** этот каталог (`<проект>/config`).
Отдельный `/etc/openvpn-logserver/config` приложение не увидит.

## database.yaml — подключение к MySQL

| Ключ | ENV | Дефолт |
|---|---|---|
| `host` | `DB_HOST` | — (обязателен, если не задан `unix_socket`) |
| `port` | `DB_PORT` | 3306 |
| `name`, `user`, `password` | `DB_NAME`, `DB_USER`, `DB_PASSWORD` | — (обязательны) |
| `unix_socket` | `DB_UNIX_SOCKET` | — |
| `pool_size`, `max_overflow` | `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 10, 20 |
| `pool_timeout`, `pool_recycle` | `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` | 30, 3600 |
| `charset` | `DB_CHARSET` | utf8mb4 |

`DATABASE_URL` в ENV перекрывает подключение целиком (`mysql+pymysql://...`).
Подстановки вида `${VAR}` внутри YAML нет — строка попадёт в конфиг буквально.

## auth.yaml — вход в веб-интерфейс

| Ключ (`auth.web.*`) | ENV |
|---|---|
| `username` | `WEB_AUTH_USERNAME` |
| `password_hash` — bcrypt, рекомендуется | `WEB_AUTH_PASSWORD_HASH` |
| `password` — открытым текстом, legacy (пишет предупреждение в лог) | `WEB_AUTH_PASSWORD` |

Если заданы оба, решает хеш. Сгенерировать хеш:

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'ПАРОЛЬ', bcrypt.gensalt()).decode())"
```

## openvpn.yaml — что читает collector

| Ключ (`openvpn.*`) | ENV | Дефолт | Кому нужен |
|---|---|---|---|
| `certs_dir` | `OPENVPN_CERTS_DIR` | `/etc/openvpn/certs` | `cert_sync` (роли all/central) |
| `cert_extension` | `OPENVPN_CERT_EXTENSION` | `.crt` | `cert_sync` |
| `crl_file` | `OPENVPN_CRL_FILE` | `/etc/openvpn/crl.pem` | `crl_checker` (роли all/central) |
| `ccd_dir` | `OPENVPN_CCD_DIR` | `/etc/openvpn/ccd` | `ccd_checker` (роли all/site) |
| `management_socket` | `OPENVPN_MGMT_SOCKET` | `/var/run/openvpn/mgmt.sock` | `session_cleanup` (роли all/site) |
| `server_name` | `OPENVPN_SERVER_NAME` | `local` | хуки и синк роли all/site |

- Роли синка и какой хост какими ключами пользуется — [docs/multisite.md](../docs/multisite.md).
- `base_dir` (`OPENVPN_BASE_DIR`) на пути не влияет: у каждого пути свой явный
  дефолт.
- Устаревшие ENV-алиасы `CERTS_DIR`, `CRL_FILE`, `CCD_DIR`, `CERT_EXTENSION`
  всё ещё читаются collector'ом и **перекрывают** одноимённые `OPENVPN_*`.
  Если в окружении остался старый `CCD_DIR`, новый `OPENVPN_CCD_DIR` не
  подействует. `OPENVPN_DIR` на пути фактически не влияет.
- Пути должны совпадать с server.conf и раскладкой PKI. Например, provision
  кладёт сертификаты как `certs/*.pem` (имя файла = серийник): при дефолтном
  `cert_extension: .crt` `cert_sync` не найдёт ни одного.

## web.yaml — только веб-приложение

Читается напрямую из `web/main.py`, в обход `core/config.py`. Используются
только два блока:

- `app.debug` — `true` открывает `/docs`, `/redoc`, `/openapi.json`. В проде —
  `false`. ENV-переопределения нет.
- `cors.allow_origins` / `allow_methods` / `allow_headers`. ENV
  `CORS_ALLOW_ORIGINS` (через запятую) перекрывает список origins. Значение
  `["*"]` вместе с credentials небезопасно — CORS тогда отключается целиком.

Хост, порт и число воркеров задаются в командной строке uvicorn (systemd-юнит
`openvpn-web.service`), а не здесь.

## Прочие ENV вне YAML

| ENV | Кто читает | Назначение |
|---|---|---|
| `SESSION_COOKIE_SECURE` | web | `true` — cookie сессии только по HTTPS (за reverse proxy с TLS) |
| `SYNC_ROLE` | `collector/sync_all.py` | роль синка `all`/`central`/`site`; флаг `--role` приоритетнее |
| `SYNC_LOCK_PATH` | `collector/sync_all.py` | lock-файл синка, дефолт `/var/run/openvpn-logserver/sync.lock`; на хосте с двумя инстансами — свой у каждого |
| `OPENVPN_LOGSERVER_PATH` | обёртки хуков | путь к проекту, дефолт `/opt/openvpn-logserver`; хукам передаётся `setenv` в server.conf |

## Права на файлы

`database.yaml` содержит пароль, но его должны читать **все** процессы,
которые ходят в БД: web, синк и хуки. Хуки выполняются от пользователя
процесса OpenVPN; при `user nobody` в server.conf это `nobody`. Если закрыть
файл правами `600`/`640` на чужого владельца, хук не прочитает конфиг: VPN
продолжит работать (fail-open), но сессии перестанут записываться молча.
Ошибку видно в `client-connect.log`. Давайте права на чтение группе, в которую
входят пользователь OpenVPN и пользователь сервисов.

## В коде и тестах

Конфигурация кешируется (`lru_cache`). После смены ENV в тестах —
`core.config.reload_config()` (возвращает `None`, конфиг перечитывается при
следующем обращении). Порядок в conftest: сначала выставить ENV, затем
импортировать `web.main`/`core.database` — иначе закешируется реальный конфиг.
