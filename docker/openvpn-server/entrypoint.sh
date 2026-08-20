#!/bin/bash
# =============================================================================
# Entrypoint скрипт для OpenVPN сервера
# =============================================================================
# Генерирует PKI при первом запуске и запускает OpenVPN сервер
#
# Исправления:
# - Убраны конфликтующие --dev tun0 и --server параметры (они переопределяли server.conf)
# - Добавлена проверка и создание /dev/net/tun если не существует
# - Улучшен error handling
# - Используется ECDH вместо DH для быстрой генерации
#
# Инварианты:
# - I9.2: OpenVPN сервер генерирует PKI при первом запуске
# =============================================================================

# Не используем set -e глобально, чтобы скрипт мог обрабатывать ошибки graceful
# set -e

# Настройки PKI
PKI_DIR="/etc/openvpn/pki"
# easy-rsa при init-pki делает hard reset — удаляет свой каталог целиком.
# Точку монтирования тома снести нельзя ("Resource busy"), поэтому PKI
# живёт в подкаталоге тома, а не в его корне.
EASYRSA_PKI_DIR="$PKI_DIR/easyrsa"
EASYRSA_DIR="/usr/share/easy-rsa"
CERTS_DIR="/etc/openvpn/certs"
CCD_DIR="/etc/openvpn/ccd"
MGMT_SOCKET_DIR="/run/openvpn"
MGMT_SOCKET_PATH="$MGMT_SOCKET_DIR/mgmt.sock"

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
    cd "$EASYRSA_DIR" || { log "ERROR: Cannot cd to $EASYRSA_DIR"; return 1; }
    
    # Создаем директории если их нет
    mkdir -p "$PKI_DIR" || { log "ERROR: Cannot create $PKI_DIR"; return 1; }
    
    # Инициализируем PKI в неинтерактивном режиме
    export EASYRSA_BATCH=1
    export EASYRSA_SKIP_CONFIRM=1

    # ВАЖНО: без EASYRSA_PKI easyrsa создаёт pki относительно своего каталога
    # (/usr/share/easy-rsa/pki), то есть ВНЕ тома openvpn_pki. Проверка
    # «PKI уже существует» смотрит в $PKI_DIR и всегда срабатывала как
    # «нет PKI» — каждое пересоздание контейнера выпускало новый CA, тогда как
    # клиентские сертификаты в томе оставались от старого.
    export EASYRSA_PKI="$EASYRSA_PKI_DIR"
    
    log "Initializing PKI..."
    ./easyrsa init-pki || { log "ERROR: Failed to init PKI"; return 1; }
    
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
    
    ./easyrsa --batch --vars=/tmp/vars build-ca nopass || { log "ERROR: Failed to build CA"; return 1; }
    
    # Создаем сертификат сервера
    log "Creating server certificate..."
    ./easyrsa --batch build-server-full server nopass || { log "ERROR: Failed to build server cert"; return 1; }
    
    # Создаем сертификат клиента (для тестирования)
    log "Creating client certificate..."
    ./easyrsa --batch build-client-full test-client nopass || { log "ERROR: Failed to build client cert"; return 1; }
    
    # Генерируем CRL
    log "Generating CRL..."
    ./easyrsa gen-crl || { log "WARNING: Failed to generate CRL, continuing..."; }
    
    # Вместо DH параметров используем ECDH для ускорения генерации
    # ECDH с prime256v1 генерируется мгновенно (вместо >2 минут для DH 2048-bit)
    log "Generating ECDH parameters (quick)..."
    openssl ecparam -name prime256v1 -genkey -noout -out "$PKI_DIR/ecdh.key" 2>/dev/null || true
    openssl ecparam -name prime256v1 -out "$PKI_DIR/ecdh.pem" 2>/dev/null || true

    # ta.key для tls-auth храним в томе: /etc/openvpn — обычная файловая
    # система контейнера, она исчезает при пересоздании, а PKI остаётся.
    log "Generating ta.key for TLS auth..."
    openvpn --genkey secret "$PKI_DIR/ta.key" || { log "ERROR: Failed to generate ta.key"; return 1; }

    log "PKI generation completed!"
    return 0
}

# Раскладывает артефакты из тома по рабочим каталогам.
# Вызывается ВСЕГДА, а не только после генерации: /etc/openvpn и $CERTS_DIR
# живут в файловой системе контейнера и пропадают при его пересоздании, тогда
# как PKI в томе сохраняется. Без этого шага пересозданный контейнер падал с
# "Cannot pre-load keyfile (/etc/openvpn/ta.key)".
install_certs_from_pki() {
    log "Installing certificates from PKI volume..."

    cp "$EASYRSA_PKI_DIR/ca.crt" /etc/openvpn/ || { log "ERROR: Failed to copy ca.crt"; return 1; }
    cp "$EASYRSA_PKI_DIR/issued/server.crt" /etc/openvpn/ || { log "ERROR: Failed to copy server.crt"; return 1; }
    cp "$EASYRSA_PKI_DIR/private/server.key" /etc/openvpn/ || { log "ERROR: Failed to copy server.key"; return 1; }
    cp "$PKI_DIR/ta.key" /etc/openvpn/ || { log "ERROR: Failed to copy ta.key"; return 1; }

    [ -f "$PKI_DIR/ecdh.pem" ] && cp "$PKI_DIR/ecdh.pem" /etc/openvpn/ 2>/dev/null
    [ -f "$PKI_DIR/ecdh.key" ] && cp "$PKI_DIR/ecdh.key" /etc/openvpn/ 2>/dev/null

    if [ -f "$EASYRSA_PKI_DIR/crl.pem" ]; then
        cp "$EASYRSA_PKI_DIR/crl.pem" /etc/openvpn/ || { log "WARNING: Failed to copy crl.pem"; }
    fi

    # Клиентские сертификаты — в общий том с openvpn-client
    mkdir -p "$CERTS_DIR"
    cp "$EASYRSA_PKI_DIR/ca.crt" "$CERTS_DIR/" || { log "WARNING: Failed to copy client ca.crt"; }
    cp "$EASYRSA_PKI_DIR/issued/test-client.crt" "$CERTS_DIR/" || { log "WARNING: Failed to copy client cert"; }
    cp "$EASYRSA_PKI_DIR/private/test-client.key" "$CERTS_DIR/" || { log "WARNING: Failed to copy client key"; }
    cp "$PKI_DIR/ta.key" "$CERTS_DIR/" || { log "WARNING: Failed to copy ta.key to CERTS_DIR"; }

    chmod 755 "$CERTS_DIR" 2>/dev/null || true
    chmod 644 "$CERTS_DIR"/* 2>/dev/null || true

    log "Certificates installed"
    return 0
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
    
    # Ждем пока MySQL станет доступен (используем nc)
    local max_attempts=30
    local attempt=1
    while [ $attempt -le $max_attempts ]; do
        if nc -z "$DB_HOST" 3306 2>/dev/null; then
            log "MySQL is ready!"
            return 0
        fi
        log "MySQL is not ready yet (attempt $attempt/$max_attempts), waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    log "WARNING: MySQL did not become ready in time, continuing anyway..."
    return 0  # Не блокируем запуск, пусть healthcheck решит
}

# Функция создания CCD файла для клиента
create_ccd_file() {
    log "Creating CCD file for test-client..."
    
    mkdir -p "$CCD_DIR"
    
    cat > "$CCD_DIR/test-client" << 'EOF'
# Client Config Directory file for test-client
# Static IP assignment
ifconfig-push 10.8.0.2 255.255.255.0

# Push specific routes
push "route 192.168.100.0 255.255.255.0"
EOF
    
    chmod 644 "$CCD_DIR/test-client"
    log "CCD file created"
}

# Функция обновления CRL
refresh_crl_if_stale() {
    # CRL, выпущенный easy-rsa, имеет срок годности (EASYRSA_CRL_DAYS, по
    # умолчанию 180 дней). Если его не обновлять, по истечении срока OpenVPN
    # начнёт отклонять ВСЕХ клиентов — отказ выглядит как проблема с
    # сертификатами и долго диагностируется. Обновляем не чаще раза в сутки.
    crl_file="/etc/openvpn/crl.pem"

    if [ -f "$crl_file" ] && [ -z "$(find "$crl_file" -mtime +1 2>/dev/null)" ]; then
        return 0
    fi

    if (cd "$EASYRSA_DIR" && EASYRSA_BATCH=1 EASYRSA_PKI="$EASYRSA_PKI_DIR" ./easyrsa gen-crl >/dev/null 2>&1); then
        cp "$EASYRSA_PKI_DIR/crl.pem" "$crl_file" 2>/dev/null && log "CRL refreshed"
    else
        log "WARNING: CRL refresh failed"
    fi
}

# Функция проверки/создания TUN устройства
setup_tun_device() {
    log "Setting up TUN device..."
    
    # Проверяем существует ли /dev/net/tun
    if [ ! -c /dev/net/tun ]; then
        log "Creating /dev/net/tun device..."
        # Создаем директорию если не существует
        mkdir -p /dev/net
        # Создаем символическую ссылку или устройство
        if [ -e /dev/net/tun ]; then
            log "/dev/net/tun exists but is not a device"
        else
            # Пытаемся создать устройство через mknod (может не работать в контейнере без privileges)
            mknod /dev/net/tun c 10 200 2>/dev/null || {
                log "Cannot create /dev/net/tun (may need privileged mode)"
            }
        fi
    else
        log "/dev/net/tun device is ready"
    fi
    
    # Проверяем доступность
    if [ -c /dev/net/tun ]; then
        chmod 666 /dev/net/tun 2>/dev/null || true
        return 0
    else
        log "WARNING: /dev/net/tun is not available"
        return 1
    fi
}

# Функция настройки iptables
setup_iptables() {
    log "Setting up iptables rules..."
    
    # Включаем forwarding
    echo 1 > /proc/sys/net/ipv4/ip_forward 2>/dev/null || true
    
    # Добавляем NAT правило для VPN сети
    # Используем || true чтобы не блокировать при ошибках
    iptables -t nat -C POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE 2>/dev/null || true
    
    log "iptables rules configured"
}

# Основная логика
main() {
    log "Starting OpenVPN Server setup..."
    
    # Создаем необходимые директории
    mkdir -p "$CERTS_DIR" "$CCD_DIR" "$MGMT_SOCKET_DIR" || {
        log "ERROR: Cannot create required directories"
        exit 1
    }
    
    # Устанавливаем права на директорию сокета
    chmod 755 "$MGMT_SOCKET_DIR"
    
    # Проверяем/создаем TUN устройство
    setup_tun_device || {
        log "WARNING: TUN device setup failed, continuing..."
    }
    
    # Проверяем, существует ли уже PKI
    if [ ! -f "$EASYRSA_PKI_DIR/ca.crt" ]; then
        log "PKI not found, generating new PKI..."
        generate_pki || {
            log "ERROR: PKI generation failed"
            exit 1
        }
        create_ccd_file
    else
        log "PKI already exists, skipping generation..."
        # Убеждаемся что CCD файл существует
        if [ ! -f "$CCD_DIR/test-client" ]; then
            create_ccd_file
        fi
    fi

    # Раскладываем сертификаты из тома в рабочие каталоги — на каждом старте,
    # т.к. /etc/openvpn не переживает пересоздание контейнера (см. функцию).
    install_certs_from_pki || {
        log "ERROR: Failed to install certificates from PKI"
        exit 1
    }

    # Ждем MySQL
    wait_for_mysql
    
    # Настраиваем iptables
    setup_iptables
    
    # Создаем директорию для логов
    mkdir -p /var/log/openvpn /var/log/openvpn-logserver
    touch /var/log/openvpn/openvpn.log /var/log/openvpn/openvpn-status.log
    
    # Периодическая синхронизация — аналог systemd-таймера openvpn-sync.timer
    # на проде. Без неё в стенде не проверяется основной фоновый контур
    # (cert_sync -> crl_checker -> ccd_checker -> session_cleanup), и запускать
    # его приходилось руками через docker exec.
    # SYNC_INTERVAL=0 отключает цикл.
    SYNC_INTERVAL="${SYNC_INTERVAL:-300}"
    if [ "$SYNC_INTERVAL" -gt 0 ] 2>/dev/null; then
        log "Periodic sync enabled: every ${SYNC_INTERVAL}s"
        (
            while true; do
                sleep "$SYNC_INTERVAL"
                refresh_crl_if_stale
                python3 /app/collector/sync_all.py \
                    >> /var/log/openvpn-logserver/sync.log 2>&1 \
                    || log "sync_all завершился с ошибкой (см. sync.log)"
            done
        ) &
    else
        log "Periodic sync disabled (SYNC_INTERVAL=0)"
    fi

    log "Starting OpenVPN server..."
    
    # ЗАПУСК OpenVPN
    # ВАЖНО: Не используем --dev tun0 и --server - они конфликтуют с server.conf
    # server.conf уже содержит все необходимые настройки:
    # - dev tun
    # - server 10.8.0.0 255.255.255.0
    # - management unix-socket /run/openvpn/mgmt.sock
    
    exec openvpn --config /etc/openvpn/server.conf \
        --cd /etc/openvpn
}

# Запускаем основную логику
main "$@"
