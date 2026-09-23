# Обёртки хуков OpenVPN

`client-connect` и `client-disconnect` — то, что OpenVPN вызывает на каждое
подключение и отключение клиента. Сами хуки — `collector/client_connect.py` и
`collector/client_disconnect.py`; обёртки делают две вещи:

1. добавляют проект в `sys.path` — путь из ENV `OPENVPN_LOGSERVER_PATH`, по
   умолчанию `/opt/openvpn-logserver`. Без этого `import core` из
   `/etc/openvpn/scripts/` не находится;
2. перехватывают **любой** сбой импорта и выполнения и выходят с кодом 0
   (инвариант I4.5). Ненулевой код из `client-connect` заставляет OpenVPN
   отказать клиенту в подключении. Ошибка конфига, недоступная БД или
   недостающая зависимость должны стоить потерянной записи в журнале, а не
   VPN.

Поэтому обёртки **копируются из репозитория, а не пишутся вручную**:
самодельная обёртка без перехвата ошибок превращает любой сбой LogServer в
отказ VPN.

## Установка

```bash
mkdir -p /etc/openvpn/scripts
cp collector/openvpn_scripts/client-connect collector/openvpn_scripts/client-disconnect /etc/openvpn/scripts/
chmod 755 /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
```

**Интерпретатор.** Шебанг — `#!/usr/bin/env python3`, системный Python.
Если зависимости ставились в venv, системный Python их не найдёт: обёртка
выйдет с 0, VPN будет работать, но данные собираться не будут. В этом случае
переключите шебанг на venv:

```bash
sed -i '1s|.*|#!/opt/openvpn-logserver/venv/bin/python|' \
    /etc/openvpn/scripts/client-connect /etc/openvpn/scripts/client-disconnect
```

**Переводы строк — только LF.** При CRLF шебанг читается как `python3\r`,
интерпретатор не находится, скрипт возвращает ненулевой код, и OpenVPN
отказывает клиентам. В репозитории это обеспечивает `.gitattributes`; при
копировании с Windows проверяйте: `file client-connect` не должен говорить
`with CRLF`.

## server.conf

```
script-security 2
client-connect    /etc/openvpn/scripts/client-connect
client-disconnect /etc/openvpn/scripts/client-disconnect
```

Без `script-security 2` хуки не исполняются. Переменные клиента
(`common_name`, `trusted_ip`, `tls_serial_0`, `bytes_*` …) OpenVPN передаёт
хукам сам — `setenv-safe` для них не нужен и вреден: он добавляет к имени
префикс `OPENVPN_`, и хук переменную не увидит.

Свои переменные для хуков задаются директивой `setenv` в том же server.conf,
потому что `export` в shell до процесса OpenVPN под systemd не доходит:

```
setenv OPENVPN_SERVER_NAME chl                          # имя инстанса (мультисайт)
setenv OPENVPN_LOGSERVER_PATH /srv/openvpn-logserver    # нестандартный путь проекта
```

Полный список требований к server.conf, в том числе `management` для очистки
оборванных сессий, — [docs/openvpn-setup.md](../../docs/openvpn-setup.md);
мультисайт — [docs/multisite.md](../../docs/multisite.md).

## Права

Хуки выполняются от пользователя процесса OpenVPN, при `user nobody` в
server.conf — от `nobody`. Этому пользователю нужно право читать
`config/database.yaml`. Иначе подключение к БД не состоится и сессии молча
перестанут записываться — ошибка будет только в `client-connect.log`.
