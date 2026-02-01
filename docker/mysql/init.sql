-- =============================================================================
-- OpenVPN LogServer - Database Initialization
-- =============================================================================
-- Этот скрипт выполняется при первом запуске MySQL контейнера
-- Создает все необходимые таблицы для работы OpenVPN LogServer
-- =============================================================================

-- Используем базу данных
USE openvpn_logs;

-- -----------------------------------------------------------------------------
-- Таблица accounts - справочник аккаунтов OpenVPN
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cn VARCHAR(255) NOT NULL COMMENT 'Common Name сертификата',
    valid_from DATETIME NULL COMMENT 'Срок начала действия сертификата',
    valid_to DATETIME NULL COMMENT 'Срок окончания действия сертификата',
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Отозван по CRL',
    revoked_at DATETIME NULL COMMENT 'Дата отзыва (из CRL)',
    has_ccd BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Наличие CCD файла',
    ccd_updated_at DATETIME NULL COMMENT 'Дата последней проверки CCD',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_cn (cn),
    INDEX idx_valid_to (valid_to),
    INDEX idx_is_revoked (is_revoked),
    INDEX idx_has_ccd (has_ccd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Справочник аккаунтов OpenVPN';

-- -----------------------------------------------------------------------------
-- Таблица sessions - журнал VPN сессий
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED NOT NULL COMMENT 'ID аккаунта',
    session_id VARCHAR(100) NULL COMMENT 'Внутренний ID сессии OpenVPN',
    connected_at DATETIME NOT NULL COMMENT 'Время подключения',
    disconnected_at DATETIME NULL COMMENT 'Время отключения (NULL = активна)',
    source_ip VARCHAR(45) NOT NULL COMMENT 'IP источника (IPv4/IPv6)',
    country VARCHAR(100) NULL COMMENT 'Страна по GeoIP',
    city VARCHAR(100) NULL COMMENT 'Город по GeoIP',
    bytes_sent BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Отправлено байт',
    bytes_received BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Получено байт',
    virtual_ip VARCHAR(45) NULL COMMENT 'Выделенный VPN IP клиента',
    status ENUM('active', 'closed', 'error') NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    INDEX idx_account_id (account_id),
    INDEX idx_connected_at (connected_at),
    INDEX idx_disconnected_at (disconnected_at),
    INDEX idx_status (status),
    INDEX idx_source_ip (source_ip)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Журнал VPN сессий';

-- -----------------------------------------------------------------------------
-- Таблица connection_attempts - неудачные попытки подключения
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS connection_attempts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED NULL COMMENT 'ID аккаунта (NULL если не удалось определить)',
    attempted_at DATETIME NOT NULL COMMENT 'Время попытки',
    source_ip VARCHAR(45) NOT NULL COMMENT 'IP источника',
    cert_cn VARCHAR(255) NULL COMMENT 'CN из предъявленного сертификата',
    failure_reason VARCHAR(255) NOT NULL COMMENT 'Причина отказа',
    failure_type ENUM('auth_failed', 'cert_revoked', 'cert_expired', 'ccd_missing', 'tls_error', 'other') NOT NULL DEFAULT 'other',
    details TEXT NULL COMMENT 'Дополнительные детали ошибки',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    INDEX idx_account_id (account_id),
    INDEX idx_attempted_at (attempted_at),
    INDEX idx_source_ip (source_ip),
    INDEX idx_failure_type (failure_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Неудачные попытки подключения';

-- -----------------------------------------------------------------------------
-- Таблица geoip_cache - кэш GeoIP данных
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geoip_cache (
    ip VARCHAR(45) NOT NULL PRIMARY KEY COMMENT 'IP адрес',
    country VARCHAR(100) NULL COMMENT 'Страна',
    country_code VARCHAR(2) NULL COMMENT 'Код страны ISO',
    city VARCHAR(100) NULL COMMENT 'Город',
    region VARCHAR(100) NULL COMMENT 'Регион/область',
    latitude DECIMAL(10, 8) NULL COMMENT 'Широта',
    longitude DECIMAL(11, 8) NULL COMMENT 'Долгота',
    isp VARCHAR(255) NULL COMMENT 'Провайдер',
    cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NULL COMMENT 'Срок действия кэша',
    
    INDEX idx_cached_at (cached_at),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Кэш GeoIP данных';

-- -----------------------------------------------------------------------------
-- Создаем тестового пользователя для Web UI (опционально)
-- -----------------------------------------------------------------------------
-- Пароль: admin (bcrypt hash)
-- Для production измените пароль!
-- INSERT INTO accounts (cn, created_at, updated_at) VALUES 
--     ('admin', NOW(), NOW()),
--     ('test-client', NOW(), NOW());
