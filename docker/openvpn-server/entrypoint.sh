#!/bin/bash
# =============================================================================
# Entrypoint скрипт для OpenVPN сервера
# =============================================================================
# Генерирует PKI при первом запуске и запускает OpenVPN сервер
# 
# Инварианты:
# - I9.2: OpenVPN сервер генерирует PKI при первом запуске
# =============================================================================

set -e

# Настройки PKI
PKI_DIR="/etc/openvpn/pki"
EASYRSA_DIR="/usr/share/easy-rsa"
CERTS_DIR="/etc/openvpn/certs"
CCD_DIR="/etc/openvpn/ccd"

# Настройки сертификатов (можно переопределить через env)
KEY_COUNTRY="${KEY_COUNTRY:-RU}"
KEY_PROVINCE="${KEY_PROVINCE:-MSK}"
KEY_CITY="${KEY_CITY:-Moscow}"
KEY_ORG="${KEY_ORG:-OpenVPN-LogServer}"
KEY_EMAIL="${KEY_EMAIL:-admin@example.com}"
KEY_OU="${KEY_OU:-IT}"
KEY_NAME="${KEY_NAME:-server}"

# Функция для логирования
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Функция генерации PKI
generate_pki() {
    log "Generating PKI infrastructure..."
    
    # Инициализируем PKI
    cd "$EASYRSA_DIR"
    
    # Создаем директории если их нет
    mkdir -p "$PKI_DIR"
    
    # Инициализируем PKI
    ./easyrsa init-pki
    
    # Создаем CA
    log "Creating Certificate Authority..."
    cat > /tmp/vars << EOF
set_var EASYRSA_REQ_COUNTRY    "$KEY_COUNTRY"
set_var EASYRSA_REQ_PROVINCE   "$KEY_PROVINCE"
set_var EASYRSA_REQ_CITY       "$KEY_CITY"
set_var EASYRSA_REQ_ORG        "$KEY_ORG"
set_var EASYRSA_REQ_EMAIL      "$KEY_EMAIL"
set_var EASYRSA_REQ_OU         "$KEY_OU"
set_var EASYRSA_REQ_CN         "OpenVPN-CA"
set_var EASYRSA_ALGO           "ec"
set_var EASYRSA_DIGEST         "sha512"
EOF
    
    ./easyrsa --batch --vars=/tmp/vars build-ca nopass
    
    # Создаем сертификат сервера
    log "Creating server certificate..."
    ./easyrsa --batch build-server-full server nopass
    
    # Создаем сертификат клиента (для тестирования)
    log "Creating client certificate..."
    ./easyrsa --batch build-client-full test-client nopass
    
    # Генерируем DH параметры (для TLS)
    log "Generating DH parameters (this may take a while)..."
    ./easyrsa gen-dh
    
    # Генерируем CRL
    log "Generating CRL..."
    ./easyrsa gen-crl
    
    # Копируем файлы в нужные места
    cp "$PKI_DIR/ca.crt" /etc/openvpn/
    cp "$PKI_DIR/issued/server.crt" /etc/openvpn/
    cp "$PKI_DIR/private/server.key" /etc/openvpn/
    cp "$PKI_DIR/dh.pem" /etc/openvpn/
    cp "$PKI_DIR/crl.pem" /etc/openvpn/
    
    # Копируем клиентские сертификаты в общую директорию
    cp "$PKI_DIR/ca.crt" "$CERTS_DIR/"
    cp "$PKI_DIR/issued/test-client.crt" "$CERTS_DIR/"
    cp "$PKI_DIR/private/test-client.key" "$CERTS_DIR/"
    
    # Создаем ta.key для tls-auth
    openvpn --genkey secret /etc/openvpn/ta.key
    cp /etc/openvpn/ta.key "$CERTS_DIR/"
    
    # Устанавливаем права
    chmod 755 "$CERTS_DIR"
    chmod 644 "$CERTS_DIR"/*
    
    log "PKI generation completed!"
}

# Функция ожидания MySQL
wait_for_mysql() {
    log "Waiting for MySQL to be ready..."
    
    # Парсим DATABASE_URL для получения параметров подключения
    # Формат: mysql+pymysql://user:password@host:port/database
    DB_URL="${DATABASE_URL:-mysql+pymysql://openvpn:openvpn_password@mysql:3306/openvpn_logs}"
    
    # Извлекаем хост из DATABASE_URL
    DB_HOST=$(echo "$DB_URL" | sed -n 's/.*@\([^:]*\):.*/\1/p')
    DB_HOST="${DB_HOST:-mysql}"
    
    # Ждем пока MySQL станет доступен
    until nc -z "$DB_HOST" 3306 2>/dev/null; do
        log "MySQL is not ready yet, waiting..."
        sleep 2
    done
    
    log "MySQL is ready!"
}

# Функция создания CCD файла для клиента
create_ccd_file() {
    log "Creating CCD file for test-client..."
    
    cat > "$CCD_DIR/test-client" << 'EOF'
# Client Config Directory file for test-client
# Static IP assignment
ifconfig-push 10.8.0.2 255.255.255.0

# Push specific routes
push "route 192.168.100.0 255.255.255.0"
EOF
    
    chmod 644 "$CCD_DIR/test-client"
}

# Основная логика
main() {
    log "Starting OpenVPN Server setup..."
    
    # Создаем необходимые директории
    mkdir -p "$CERTS_DIR" "$CCD_DIR"
    
    # Проверяем, существует ли уже PKI
    if [ ! -f "$PKI_DIR/ca.crt" ]; then
        log "PKI not found, generating new PKI..."
        generate_pki
        create_ccd_file
    else
        log "PKI already exists, skipping generation..."
    fi
    
    # Ждем MySQL
    wait_for_mysql
    
    # Настраиваем iptables для NAT
    log "Setting up iptables rules..."
    iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE 2>/dev/null || true
    
    # Создаем директорию для статуса
    mkdir -p /var/log/openvpn
    touch /var/log/openvpn/openvpn-status.log
    
    log "Starting OpenVPN server..."
    
    # Запускаем OpenVPN
    exec openvpn --config /etc/openvpn/server.conf \
        --cd /etc/openvpn \
        --dev tun0 \
        --server 10.8.0.0 255.255.255.0
}

# Запускаем основную логику
main "$@"
