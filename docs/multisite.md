# Мультисайт: LogServer для нескольких OpenVPN-серверов

## Контекст

Provision-скрипты (соседний репозиторий `ovpn`, каталог `multisite/`) поддерживают
топологию «один центральный CA + несколько сайтов»:

- **Админ-хост** (не VPN-сервер): CA, база выпущенных сертификатов
  (`certs/*.pem`, имя файла = серийник), CRL (`crl/crl.pem`), каталоги клиентов
  `clients/<prefix>-<config>/` с per-site CCD (`ccd.<site>`).
- **Серверы сайтов** (`sites="chl klg mhk msk nn"`): на каждом обычно два
  инстанса OpenVPN — обычный (:1194) и 2FA (:1196). Админ-хост пушит на них по
  ssh только CCD (`/etc/openvpn/mobile/ccd/<config>`; выключенный —
  `<config>_OFF`) и секреты google-authenticator.

Следствия для LogServer:

- **сертификаты и CRL существуют только на админ-хосте** → `cert_sync` и
  `crl_checker` выполняются там;
- **сессии, CCD и management-интерфейс существуют только на серверах сайтов** →
  хуки, `ccd_checker` и `session_cleanup` выполняются там;
- CCD включён/выключен **независимо на каждом сайте** → статус CCD per-site.

## Схема размещения

```
Админ-хост (CA):   MySQL + web (FastAPI) + systemd-таймер: sync_all.py --role central
Каждый инстанс
OpenVPN на сайте:  hooks (client_connect/client_disconnect)
                   + systemd-таймер: sync_all.py --role site
Сайты → MySQL админ-хоста по сети (свой MySQL-пользователь на сайт)
```

MySQL один, центральный. Хуки fail-open (I4.5): недоступность БД не ломает VPN,
теряется только запись о сессии.

## Идентичность сервера

Каждый **инстанс** OpenVPN (2FA-инстанс — отдельно!) имеет имя в конфигурации:

```yaml
# config/openvpn.yaml на сервере сайта (или ENV OPENVPN_SERVER_NAME)
openvpn:
  server_name: chl        # у 2FA-инстанса того же хоста: chl-2fa
```

По этому имени collector автоматически регистрирует запись в таблице
`vpn_servers` — руками её заводить не нужно. Дефолт `local` оставляет
single-site установку рабочей без правки конфига.

## Изменения схемы БД (миграция 005)

| Объект | Назначение |
|---|---|
| `vpn_servers` | справочник инстансов: id, name (уникально), description |
| `sessions.server_id` | на каком сервере шла сессия; NULL — legacy-строки до мультисайта |
| `ccd_status` | per-site наличие CCD: строка = (cn, server) — файл `<cn>` есть на этом сервере; нет строки — нет CCD |

Файлы `<cn>_OFF` (архив выключенного доступа, который admin-скрипты provision
оставляют «посмотреть, какие сети маршрутизировались») checker игнорирует —
для мониторинга это отсутствие CCD.

`accounts.has_ccd` остаётся **агрегатом** «CCD есть хотя бы на одном сервере»
и пересчитывается `ccd_checker`-ом из `ccd_status` — существующие
страницы/фильтры продолжают работать.

## Скоупинг по серверу (критично для корректности)

- `session_cleanup` сравнивает с mgmt-сокетом **только сессии своего
  server_id** — иначе первый же запуск на любом сайте пометил бы `error` живые
  сессии остальных сайтов (см. docs/invariants.md, C1).
- C5.x в `client_connect` (закрытие старой active-сессии при reconnect) и
  I5.1 в `client_disconnect` скоупятся по серверу: один конфиг может легитимно
  висеть на двух сайтах одновременно.
- Legacy-сессии с `server_id IS NULL` во всех трёх местах считаются «своими»:
  они созданы до мультисайта единственным существовавшим сервером. После
  апгрейда single-site можно (не обязательно) забэкфиллить:
  `UPDATE sessions SET server_id = (SELECT id FROM vpn_servers WHERE name='local') WHERE server_id IS NULL;`

## Роли синхронизации

```bash
# Админ-хост (CA): сертификаты + CRL
python collector/sync_all.py --role central

# Сервер сайта: CCD + очистка orphaned-сессий
python collector/sync_all.py --role site

# Single-site (как раньше): всё сразу
python collector/sync_all.py
```

В systemd-юните каждого хоста указывается своя роль (ExecStart с `--role ...`).

## Конфигурация по хостам

### Админ-хост (CA)

```yaml
# config/openvpn.yaml — пути provision-раскладки админ-хоста
openvpn:
  certs_dir: /etc/openvpn/certs
  cert_extension: .pem            # provision кладёт certs/*.pem (имя = серийник)
  crl_file: /etc/openvpn/crl/crl.pem
```

Плюс `config/database.yaml` (локальный MySQL) и `config/auth.yaml` для web.

### Сервер сайта: установка сборщика (пошагово)

Сборщик — это код репозитория **без web-части**: реально используются каталоги
`collector/` и `core/` плюс `config/`. Проще всего клонировать репозиторий
целиком (web просто не запускается):

```bash
# 1. Код и окружение
sudo git clone <repo> /opt/openvpn-logserver
cd /opt/openvpn-logserver
sudo python3 -m venv venv
sudo venv/bin/pip install -r collector/requirements.txt

# 2. Каталог логов (хуки пишут сюда; владелец — тот, от кого работает openvpn)
sudo mkdir -p /var/log/openvpn-logserver
```

Конфиги (в git не коммитятся, создаются из `*.example`):

```yaml
# config/database.yaml — указывает на MySQL АДМИН-ХОСТА
database:
  host: admin-host.contoso.local
  port: 3306
  name: openvpn_logs
  user: ovpn_chl          # свой пользователь на сайт, гранты — см. ниже
  password: "..."
```

```yaml
# config/openvpn.yaml — пути этого сайта
openvpn:
  ccd_dir: /etc/openvpn/mobile/ccd          # remoteCcdDir из provision
  management_socket: /run/openvpn/mgmt-chl.sock
  server_name: chl                          # имя ЭТОГО инстанса
```

`config/auth.yaml` и `web.yaml` на сайте не нужны (web не запускается).

Хуки для OpenVPN (обёртки из `collector/openvpn_scripts/`):

```bash
sudo mkdir -p /etc/openvpn/scripts
sudo cp collector/openvpn_scripts/client-connect collector/openvpn_scripts/client-disconnect /etc/openvpn/scripts/
sudo chmod +x /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
# ВАЖНО: шебанг обёрток — /usr/bin/env python3. Зависимости стоят в venv,
# поэтому заменить первую строку обоих файлов на:
#   #!/opt/openvpn-logserver/venv/bin/python
```

В server.conf инстанса (provision не генерирует ни `management`, ни
`client-disconnect` — добавить руками, см. docs/openvpn-setup.md):

```
script-security 2                                  # у provision уже есть
management /run/openvpn/mgmt-chl.sock unix
client-connect  /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect
```

Внимание: provision уже использует `client-connect $ovpndir/route-client`
(заглушка). Директива `client-connect` может указываться несколько раз — либо
оставить обе, либо обернуть оба вызова одним скриптом. Ненулевой exit любого
client-connect блокирует подключение — хуки logserver гарантируют exit 0 (I4.5).

Периодическая синхронизация сайта (ccd_checker + session_cleanup):

```ini
# /etc/systemd/system/openvpn-sync-site.service
[Unit]
Description=OpenVPN LogServer site sync (ccd + cleanup)

[Service]
Type=oneshot
WorkingDirectory=/opt/openvpn-logserver
ExecStart=/opt/openvpn-logserver/venv/bin/python collector/sync_all.py --role site

# /etc/systemd/system/openvpn-sync-site.timer
[Unit]
Description=OpenVPN LogServer site sync timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now openvpn-sync-site.timer
```

Проверка: в UI появились сессии с именем сервера; `SELECT * FROM vpn_servers;`
содержит `chl`; `ccd_status` наполнился; cleanup в логе
(`/var/log/openvpn-logserver/session-cleanup.log`) видит клиентов mgmt.

## Два инстанса OpenVPN на одном хосте (обычный + 2FA)

**Раскладывать сборщик по двум папкам не нужно — один каталог
`/opt/openvpn-logserver` обслуживает оба инстанса.** Это работает потому, что
в самом каталоге не хранится ничего инстанс-специфичного:

- код и venv у инстансов идентичны;
- `config/database.yaml` (центральный MySQL) и `ccd_dir` общие для хоста;
- а то, что у инстансов различается — имя (`server_name`), management-сокет,
  lock-файл синка — задаётся **снаружи**, переменными окружения того процесса,
  который запускается: хукам их передаёт OpenVPN (`setenv` в server.conf),
  синку — systemd (`Environment=` в юните). ENV имеет приоритет над YAML
  (`core/config.py`), поэтому одна и та же папка ведёт себя по-разному в
  зависимости от того, кто её запустил.

Захардкоженных путей, мешающих этому, нет. Для справки — какие пути вообще
зашиты и что с ними:

| Путь | Где зашит | Примечание |
|---|---|---|
| `/opt/openvpn-logserver` | обёртки хуков `openvpn_scripts/*` (PROJECT_PATH) | меняется правкой строки или ENV `OPENVPN_LOGSERVER_PATH`; на оба инстанса один |
| `/var/run/openvpn-logserver/sync.lock` | дефолт lock-файла синка | **один на хост** → при двух инстансах обязателен свой `SYNC_LOCK_PATH` у каждого (иначе таймеры перекрываются и второй запуск молча пропускается) |
| `/var/log/openvpn-logserver/` | логи хуков/синка | общий на хост: записи обоих инстансов идут в одни файлы — это ок |

При двух инстансах различаются ровно три вещи:

| Что | Инстанс `chl` | Инстанс `chl-2fa` | Кто передаёт |
|---|---|---|---|
| `server_name` | `chl` | `chl-2fa` | хукам — `setenv` в server.conf; синку — systemd |
| management-сокет | `/run/openvpn/mgmt-chl.sock` | `/run/openvpn/mgmt-chl-2fa.sock` | синку — systemd (хукам не нужен) |
| lock-файл синка | `sync-chl.lock` | `sync-chl-2fa.lock` | systemd (`SYNC_LOCK_PATH`) |

При такой схеме в `config/openvpn.yaml` инстанс-специфичные ключи
(`server_name`, `management_socket`) можно вообще не заполнять — источником
правды для них становятся server.conf и systemd-юниты.

CCD-каталог у обоих инстансов один (`/etc/openvpn/mobile/ccd` — provision пушит
в него один раз на хост): каждый инстанс просто заведёт свои строки
`ccd_status`, содержимое совпадёт.

**Хуки.** Обёртки в `/etc/openvpn/scripts/` общие. Имя инстанса хук получает
через `setenv` в server.conf — OpenVPN передаёт такие переменные окружения в
script-хуки:

```
# server.conf обычного инстанса
setenv OPENVPN_SERVER_NAME chl
management /run/openvpn/mgmt-chl.sock unix
client-connect  /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect

# server-2fa.conf
setenv OPENVPN_SERVER_NAME chl-2fa
management /run/openvpn/mgmt-chl-2fa.sock unix
client-connect  /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect
```

(`OPENVPN_MGMT_SOCKET` хукам не нужен — сокет использует только session_cleanup.)

**Синхронизация.** Второй пары unit-файлов писать не нужно — шаблонный юнит,
инстанс = имя сервера:

```ini
# /etc/systemd/system/openvpn-sync-site@.service
[Unit]
Description=OpenVPN LogServer site sync (%i)

[Service]
Type=oneshot
WorkingDirectory=/opt/openvpn-logserver
Environment=OPENVPN_SERVER_NAME=%i
Environment=OPENVPN_MGMT_SOCKET=/run/openvpn/mgmt-%i.sock
# Дефолтный lock один на хост — у каждого инстанса свой, иначе таймеры
# будут перекрываться и второй запуск пропускаться (SyncAlreadyRunning)
Environment=SYNC_LOCK_PATH=/var/run/openvpn-logserver/sync-%i.lock
ExecStart=/opt/openvpn-logserver/venv/bin/python collector/sync_all.py --role site

# /etc/systemd/system/openvpn-sync-site@.timer
[Unit]
Description=OpenVPN LogServer site sync timer (%i)
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now openvpn-sync-site@chl.timer
sudo systemctl enable --now openvpn-sync-site@chl-2fa.timer
```

Именование сокетов должно совпадать с шаблоном `mgmt-%i.sock` — тогда один
unit-файл обслуживает все инстансы хоста. Сайт без 2FA включает только
`openvpn-sync-site@<site>.timer`.

MySQL-пользователь у обоих инстансов общий (один на сайт).

### Вариант Б: две физические копии

Если ENV-переопределения не по душе, два клона тоже работают
(`/opt/openvpn-logserver-chl` и `/opt/openvpn-logserver-chl-2fa`): у каждого
свой venv, свой `config/openvpn.yaml` с `server_name`/`management_socket`,
свои копии обёрток хуков с поправленным `PROJECT_PATH`, свой обычный (не
шаблонный) sync-юнит с `WorkingDirectory` на свою папку. Два подводных камня
остаются и здесь, потому что зашиты не в папку, а в хост: lock-файл синка
(`SYNC_LOCK_PATH` всё равно задать разными) и общий каталог логов. Вариант с
одной папкой предпочтительнее: одно обновление кода и зависимостей вместо двух.

## MySQL: доступ с сайтов

По пользователю на сайт, минимальные гранты (хукам нужны INSERT/UPDATE/SELECT):

```sql
CREATE USER 'ovpn_chl'@'10.32.0.%' IDENTIFIED BY '...';
GRANT SELECT, INSERT, UPDATE ON openvpn_logs.accounts     TO 'ovpn_chl'@'10.32.0.%';
GRANT SELECT, INSERT, UPDATE ON openvpn_logs.sessions     TO 'ovpn_chl'@'10.32.0.%';
GRANT SELECT, INSERT, UPDATE ON openvpn_logs.vpn_servers  TO 'ovpn_chl'@'10.32.0.%';
GRANT SELECT, INSERT, UPDATE, DELETE ON openvpn_logs.ccd_status TO 'ovpn_chl'@'10.32.0.%';
GRANT SELECT, INSERT, UPDATE ON openvpn_logs.geoip_cache  TO 'ovpn_chl'@'10.32.0.%';
```

(DELETE только на `ccd_status`: checker удаляет строки исчезнувших файлов.)
Сетевой доступ 3306 с сайтов до админ-хоста ограничить firewall'ом; желательно
TLS (`REQUIRE SSL`).

## Миграция существующей single-site установки

Апгрейд работающей установки на версию с мультисайтом — независимо от того,
будет ли дальше разворачиваться мультисайт. Всё на одном хосте, как и было;
имя узла — любое осмысленное (`local` — лишь дефолт, не обязанность).

```bash
# 1. Код + схема (сразу друг за другом: код с новой моделью против старой
#    схемы неработоспособен. Хуки в этом промежутке fail-open — VPN живёт,
#    но события подключений теряются, поэтому пауза должна быть короткой)
cd /opt/openvpn-logserver
sudo git pull
sudo venv/bin/alembic -c database/alembic.ini upgrade head   # применит 005

# 2. Имя узла — добавить ключ server_name в секцию openvpn:
#    файла config/openvpn.yaml (НЕ в обёртках хуков, их не трогаем):
#        openvpn:
#          ...
#          server_name: msk
#    Хуки — короткоживущие процессы, читают конфиг при каждом запуске:
#    ни OpenVPN, ни что-либо ещё перезапускать не нужно

# 3. Перезапустить web (единственный долгоживущий процесс со старым кодом)
sudo systemctl restart openvpn-web
```

Дальше всё происходит само: первое же подключение клиента (или ближайший
запуск sync-таймера) создаст запись в `vpn_servers`, новые сессии пойдут с
`server_id`. Systemd-юнит синка менять не нужно — `sync_all.py` без `--role`
работает как раньше (все четыре шага).

Старые сессии остаются с `server_id IS NULL`: логика (cleanup, reconnect)
считает их «своими», так что это безвредно, но в UI они показываются с
сервером `-`. Чтобы история выглядела единообразно — после того как запись в
`vpn_servers` появилась (проверить: `SELECT * FROM vpn_servers;`), один раз:

```sql
UPDATE sessions
SET server_id = (SELECT id FROM vpn_servers WHERE name = 'msk')
WHERE server_id IS NULL;
```

(Если ждать первого подключения не хочется, запись можно создать и руками:
`INSERT INTO vpn_servers (name) VALUES ('msk');` — имя должно совпадать с
`server_name` из конфига.)

Проверка после миграции: `/api/v1/servers` показывает узел; у новой сессии в
UI заполнен Server; на карточке пользователя CCD показан бейджем узла.

## Порядок внедрения

1. Админ-хост: MySQL, `alembic upgrade head` (005), web, таймер
   `--role central`. Проверить, что accounts наполнились из `certs/*.pem` и
   CRL подхватился.
2. Один пилотный инстанс сайта: конфиг с `server_name`, server.conf
   (management + хуки), таймер `--role site`. Проверить: сессии в UI с именем
   сервера; cleanup не трогает чужие сессии; `ccd_status` наполнился.
3. Раскатать остальные инстансы по одному.
4. Опционально: бэкфилл `server_id` для старых сессий (см. выше).

## API/UI

- `GET /api/v1/servers` — список инстансов.
- `GET /api/v1/sessions?server=<name>` — фильтр по серверу; в элементах сессий
  везде добавлено `server_name` (NULL у legacy).
- `GET /api/v1/accounts/{cn}` — поле `ccd_sites`: на каких серверах у CN есть
  CCD-файл.
- UI: колонка и фильтр Server на странице сессий, бейджи серверов с CCD на
  карточке аккаунта, сервер в деталях сессии, колонка server в CSV-экспорте.

## Известные ограничения

- Учёт трафика при обрыве: bytes_* пишутся только штатным disconnect-хуком —
  как и в single-site.
- Буферизации записи хуков при недоступной центральной БД нет: событие
  теряется (fail-open). При необходимости — отдельная доработка (локальный
  спул + догрузка).
- CRL на серверы сайтов provision не доставляет — отзыв сертификата виден в
  LogServer (central crl_checker), но фактически не блокирует подключение на
  сайте, пока туда не доставлен свежий файл для `crl-verify`. Это дыра provision,
  не LogServer — рекомендуется закрыть в provision (push CRL вместе с CCD).
