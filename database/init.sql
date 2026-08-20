-- Инициализация базы данных OpenVPN LogServer
-- Запускать: mysql -u root -p < database/init.sql

-- Создание базы данных
CREATE DATABASE IF NOT EXISTS openvpn_logs
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE openvpn_logs;

-- Создание пользователя (замените 'your_secure_password' на реальный пароль)
CREATE USER IF NOT EXISTS 'ovpn_collector'@'localhost'
    IDENTIFIED BY 'your_secure_password';

-- Предоставление прав
GRANT ALL PRIVILEGES ON openvpn_logs.* TO 'ovpn_collector'@'localhost';

-- Применение изменений
FLUSH PRIVILEGES;

-- ВНИМАНИЕ: канонический источник схемы — миграции Alembic (database/migrations)
-- и core/models.py. Этот файл держится в соответствии со схемой на ревизии 002
-- (serial_number + uk_cn_serial) для ручного bootstrap без Alembic. При новых
-- миграциях обновлять здесь согласованно ИЛИ разворачивать через `alembic upgrade head`.

-- Таблица accounts (справочник аккаунтов; уникальность по паре cn+serial_number)
CREATE TABLE IF NOT EXISTS accounts (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cn VARCHAR(255) NOT NULL,
    serial_number VARCHAR(64) NOT NULL DEFAULT 'unknown',
    valid_from DATETIME,
    valid_to DATETIME,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at DATETIME,
    has_ccd BOOLEAN NOT NULL DEFAULT FALSE,
    ccd_updated_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_cn_serial (cn, serial_number),
    INDEX idx_cn (cn),
    INDEX idx_serial_number (serial_number),
    INDEX idx_valid_to (valid_to),
    INDEX idx_is_revoked (is_revoked),
    INDEX idx_has_ccd (has_ccd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Таблица sessions (журнал VPN сессий)
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED NOT NULL,
    session_id VARCHAR(100),
    connected_at DATETIME NOT NULL,
    disconnected_at DATETIME,
    source_ip VARCHAR(45) NOT NULL,
    country VARCHAR(100),
    city VARCHAR(100),
    bytes_sent BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bytes_received BIGINT UNSIGNED NOT NULL DEFAULT 0,
    virtual_ip VARCHAR(45),
    status ENUM('active', 'closed', 'error') NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_account_id (account_id),
    INDEX idx_connected_at (connected_at),
    INDEX idx_disconnected_at (disconnected_at),
    INDEX idx_status (status),
    INDEX idx_source_ip (source_ip),
    INDEX idx_status_connected_at (status, connected_at),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Таблица connection_attempts (неудачные попытки подключения)
CREATE TABLE IF NOT EXISTS connection_attempts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED,
    attempted_at DATETIME NOT NULL,
    source_ip VARCHAR(45) NOT NULL,
    cert_cn VARCHAR(255),
    failure_reason VARCHAR(255) NOT NULL,
    failure_type ENUM('auth_failed', 'cert_revoked', 'cert_expired', 'ccd_missing', 'tls_error', 'other') NOT NULL DEFAULT 'other',
    details TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_account_id (account_id),
    INDEX idx_attempted_at (attempted_at),
    INDEX idx_source_ip (source_ip),
    INDEX idx_failure_type (failure_type),
    INDEX idx_cert_cn (cert_cn),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Таблица geoip_cache (кэш GeoIP данных)
CREATE TABLE IF NOT EXISTS geoip_cache (
    ip VARCHAR(45) PRIMARY KEY,
    country VARCHAR(100),
    country_code VARCHAR(2),
    city VARCHAR(100),
    region VARCHAR(100),
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    isp VARCHAR(255),
    cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    INDEX idx_cached_at (cached_at),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Сообщение об успешном создании
SELECT 'Database openvpn_logs initialized successfully!' AS status;
