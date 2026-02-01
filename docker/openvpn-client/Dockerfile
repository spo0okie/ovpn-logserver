# =============================================================================
# Dockerfile для OpenVPN клиента
# =============================================================================
# Создает образ OpenVPN клиента для тестирования подключения к серверу
# =============================================================================

FROM alpine:3.19

# Устанавливаем необходимые пакеты
RUN apk add --no-cache \
    openvpn \
    bash \
    curl \
    iputils \
    net-tools \
    iproute2 \
    && ln -sf /bin/bash /bin/sh

# Создаем директории для OpenVPN
RUN mkdir -p \
    /etc/openvpn \
    /etc/openvpn/client \
    /var/log/openvpn

# Копируем конфигурацию клиента
COPY docker/openvpn-client/client.conf /etc/openvpn/client/client.conf

# Копируем entrypoint скрипт
COPY docker/openvpn-client/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Открываем необходимые capabilities
RUN echo "user root" >> /etc/openvpn/client/client.conf

ENTRYPOINT ["/entrypoint.sh"]
