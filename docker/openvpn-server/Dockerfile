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
    && ln -sf python3 /usr/bin/python

# Устанавливаем дополнительные Python пакеты
RUN pip3 install --break-system-packages --no-cache-dir \
    sqlalchemy \
    pymysql \
    cryptography \
    requests

# Создаем директории для OpenVPN
RUN mkdir -p \
    /etc/openvpn \
    /etc/openvpn/pki \
    /etc/openvpn/ccd \
    /etc/openvpn/certs \
    /var/log/openvpn \
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

# Открываем порт OpenVPN
EXPOSE 1194/udp

# Устанавливаем entrypoint
ENTRYPOINT ["/entrypoint.sh"]
