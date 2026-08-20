# =============================================================================
# Dockerfile для OpenVPN сервера
# =============================================================================
# Создает образ OpenVPN сервера с:
# - OpenVPN 2.6+
# - EasyRSA для генерации PKI
# - Python 3.11+ для collector скриптов
# - Автоматической генерацией PKI при первом запуске
# =============================================================================

FROM alpine:3.19

# Устанавливаем необходимые пакеты
# - openvpn: VPN сервер
# - easy-rsa: Утилиты для PKI
# - bash: Для entrypoint скрипта
# - curl: Для healthcheck и тестов
# - python3: Для collector скриптов
# - py3-pip, py3-pip: Python пакеты
# - ip6tables, iptables: Для настройки NAT
# - netcat-openbsd: Для проверки доступности MySQL (wait_for_mysql)
# - openssl: Для генерации ECDH параметров
RUN apk add --no-cache \
    openvpn \
    easy-rsa \
    bash \
    curl \
    python3 \
    py3-pip \
    py3-sqlalchemy \
    py3-pymysql \
    ip6tables \
    iptables \
    netcat-openbsd \
    openssl \
    && ln -sf python3 /usr/bin/python

# Python-зависимости ставим из collector/requirements.txt — единый источник.
# Раньше список был захардкожен здесь и в нём отсутствовал pyyaml, который
# импортирует core/config.py: хуки падали с ModuleNotFoundError.
COPY collector/requirements.txt /tmp/collector-requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir \
    -r /tmp/collector-requirements.txt \
    && rm -f /tmp/collector-requirements.txt

# Создаем директории для OpenVPN
RUN mkdir -p \
    /etc/openvpn \
    /etc/openvpn/pki \
    /etc/openvpn/ccd \
    /etc/openvpn/certs \
    /var/log/openvpn \
    /var/log/openvpn-logserver \
    /app/collector \
    /app/core

# Копируем collector скрипты
COPY collector/ /app/collector/
COPY core/ /app/core/

# Устанавливаем права на выполнение для скриптов
RUN chmod +x /app/collector/*.py

# Копируем конфигурацию OpenVPN
COPY docker/openvpn-server/server.conf /etc/openvpn/server.conf

# Копируем entrypoint скрипт
COPY docker/openvpn-server/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Создаем пользователя nobody для OpenVPN (требуется в server.conf)
RUN adduser -D -H -s /sbin/nologin -u 65534 -G nobody nobody 2>/dev/null || \
    adduser -D -H -s /sbin/nologin nobody 2>/dev/null || true

# Открываем порт OpenVPN
EXPOSE 1194/udp

# Устанавливаем entrypoint
ENTRYPOINT ["/entrypoint.sh"]
