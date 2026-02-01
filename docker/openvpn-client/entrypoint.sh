#!/bin/bash
# =============================================================================
# Entrypoint скрипт для OpenVPN клиента
# =============================================================================
# Ожидает доступности сервера и сертификатов, затем подключается к VPN
# 
# Инварианты:
# - I9.3: Клиент может подключиться к серверу
# =============================================================================

set -e

# Настройки
CLIENT_DIR="/etc/openvpn/client"
SERVER_HOST="${OPENVPN_SERVER:-openvpn-server}"
SERVER_PORT="${OPENVPN_PORT:-1194}"
CERTS_DIR="/etc/openvpn/certs"

# Функция для логирования
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Функция ожидания сервера
wait_for_server() {
    log "Waiting for OpenVPN server at $SERVER_HOST:$SERVER_PORT..."
    
    until nc -z "$SERVER_HOST" "$SERVER_PORT" 2>/dev/null; do
        log "Server is not ready yet, waiting..."
        sleep 2
    done
    
    log "OpenVPN server is ready!"
}

# Функция ожидания сертификатов
wait_for_certs() {
    log "Waiting for certificates..."
    
    # Ждем пока появятся сертификаты от сервера
    # В реальном сценарии сертификаты могут быть скопированы через volume
    # или сгенерированы заранее
    
    local required_files=(
        "$CERTS_DIR/ca.crt"
        "$CERTS_DIR/test-client.crt"
        "$CERTS_DIR/test-client.key"
        "$CERTS_DIR/ta.key"
    )
    
    for file in "${required_files[@]}"; do
        until [ -f "$file" ]; do
            log "Waiting for $file..."
            sleep 2
        done
        log "Found $file"
    done
    
    # Копируем сертификаты в client директорию
    cp "$CERTS_DIR/ca.crt" "$CLIENT_DIR/"
    cp "$CERTS_DIR/test-client.crt" "$CLIENT_DIR/client.crt"
    cp "$CERTS_DIR/test-client.key" "$CLIENT_DIR/client.key"
    cp "$CERTS_DIR/ta.key" "$CLIENT_DIR/"
    
    # Устанавливаем права
    chmod 600 "$CLIENT_DIR/client.key"
    chmod 644 "$CLIENT_DIR/ca.crt" "$CLIENT_DIR/client.crt" "$CLIENT_DIR/ta.key"
    
    log "Certificates are ready!"
}

# Функция генерации клиентской конфигурации
generate_client_config() {
    log "Generating client configuration..."
    
    cat > "$CLIENT_DIR/client.ovpn" << EOF
client
dev tun
proto udp
remote $SERVER_HOST $SERVER_PORT
resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server
cipher AES-256-GCM
auth SHA512

verb 3

<ca>
$(cat "$CLIENT_DIR/ca.crt")
</ca>

<cert>
$(cat "$CLIENT_DIR/client.crt")
</cert>

<key>
$(cat "$CLIENT_DIR/client.key")
</key>

key-direction 1
<tls-auth>
$(cat "$CLIENT_DIR/ta.key")
</tls-auth>
EOF
    
    chmod 644 "$CLIENT_DIR/client.ovpn"
    log "Client configuration generated!"
}

# Функция тестирования подключения
test_connection() {
    log "Testing VPN connection..."
    
    # Запускаем OpenVPN клиент в фоновом режиме
    openvpn --config "$CLIENT_DIR/client.ovpn" \
        --daemon \
        --log /var/log/openvpn/client.log \
        --writepid /var/run/openvpn.pid
    
    # Ждем установления соединения
    log "Waiting for VPN connection to establish..."
    sleep 5
    
    # Проверяем наличие tun интерфейса
    if ip link show tun0 >/dev/null 2>&1; then
        log "VPN connection established successfully!"
        ip addr show tun0
        
        # Проверяем связность с сервером
        if ping -c 3 10.8.0.1 >/dev/null 2>&1; then
            log "Successfully pinged VPN server (10.8.0.1)"
        else
            log "WARNING: Cannot ping VPN server"
        fi
        
        return 0
    else
        log "ERROR: VPN connection failed!"
        cat /var/log/openvpn/client.log
        return 1
    fi
}

# Основная логика
main() {
    log "Starting OpenVPN Client setup..."
    
    # Создаем необходимые директории
    mkdir -p "$CLIENT_DIR" "$CERTS_DIR" /var/log/openvpn
    
    # Ждем сервер
    wait_for_server
    
    # Ждем сертификаты
    wait_for_certs
    
    # Генерируем конфигурацию
    generate_client_config
    
    # Тестируем подключение
    if [ "${TEST_CONNECTION:-true}" = "true" ]; then
        test_connection
    fi
    
    # Если передан аргумент "connect", запускаем OpenVPN на переднем плане
    if [ "$1" = "connect" ]; then
        log "Starting OpenVPN client in foreground mode..."
        exec openvpn --config "$CLIENT_DIR/client.ovpn"
    fi
    
    # Иначе просто держим контейнер активным
    log "Client setup complete. Keeping container alive..."
    tail -f /var/log/openvpn/client.log 2>/dev/null || sleep infinity
}

# Запускаем основную логику
main "$@"
