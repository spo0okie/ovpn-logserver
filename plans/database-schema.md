# Схема базы данных MySQL

## Таблица: accounts

Справочник аккаунтов (CN сертификатов).

```sql
CREATE TABLE accounts (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cn VARCHAR(255) NOT NULL COMMENT 'Common Name сертификата',
    valid_from DATETIME COMMENT 'Срок начала действия сертификата',
    valid_to DATETIME COMMENT 'Срок окончания действия сертификата',
    is_revoked BOOLEAN DEFAULT FALSE COMMENT 'Отозван по CRL',
    revoked_at DATETIME COMMENT 'Дата отзыва (из CRL)',
    has_ccd BOOLEAN DEFAULT FALSE COMMENT 'Наличие CCD файла',
    ccd_updated_at DATETIME COMMENT 'Дата последней проверки CCD',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_cn (cn),
    INDEX idx_valid_to (valid_to),
    INDEX idx_is_revoked (is_revoked),
    INDEX idx_has_ccd (has_ccd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Справочник аккаунтов OpenVPN';
```

## Таблица: sessions

Журнал VPN сессий.

```sql
CREATE TABLE sessions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED NOT NULL,
    session_id VARCHAR(100) COMMENT 'Внутренний ID сессии OpenVPN',
    connected_at DATETIME NOT NULL COMMENT 'Время подключения',
    disconnected_at DATETIME COMMENT 'Время отключения (NULL = активна)',
    source_ip VARCHAR(45) NOT NULL COMMENT 'IP источника (IPv4/IPv6)',
    country VARCHAR(100) COMMENT 'Страна по GeoIP',
    city VARCHAR(100) COMMENT 'Город по GeoIP',
    bytes_sent BIGINT UNSIGNED DEFAULT 0 COMMENT 'Отправлено байт',
    bytes_received BIGINT UNSIGNED DEFAULT 0 COMMENT 'Получено байт',
    virtual_ip VARCHAR(45) COMMENT 'Выделенный VPN IP клиента',
    status ENUM('active', 'closed', 'error') DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_account_id (account_id),
    INDEX idx_connected_at (connected_at),
    INDEX idx_disconnected_at (disconnected_at),
    INDEX idx_status (status),
    INDEX idx_source_ip (source_ip),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Журнал VPN сессий';
```

## Таблица: connection_attempts

Неудачные попытки подключения.

```sql
CREATE TABLE connection_attempts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    account_id INT UNSIGNED COMMENT 'ID аккаунта (NULL если не удалось определить)',
    attempted_at DATETIME NOT NULL COMMENT 'Время попытки',
    source_ip VARCHAR(45) NOT NULL COMMENT 'IP источника',
    cert_cn VARCHAR(255) COMMENT 'CN из предъявленного сертификата',
    failure_reason VARCHAR(255) NOT NULL COMMENT 'Причина отказа',
    failure_type ENUM('auth_failed', 'cert_revoked', 'cert_expired', 
                      'ccd_missing', 'tls_error', 'other') DEFAULT 'other',
    details TEXT COMMENT 'Дополнительные детали ошибки',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_account_id (account_id),
    INDEX idx_attempted_at (attempted_at),
    INDEX idx_source_ip (source_ip),
    INDEX idx_failure_type (failure_type),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Неудачные попытки подключения';
```

## Таблица: geoip_cache

Кэш результатов GeoIP запросов.

```sql
CREATE TABLE geoip_cache (
    ip VARCHAR(45) PRIMARY KEY COMMENT 'IP адрес',
    country VARCHAR(100) COMMENT 'Страна',
    country_code VARCHAR(2) COMMENT 'Код страны ISO',
    city VARCHAR(100) COMMENT 'Город',
    region VARCHAR(100) COMMENT 'Регион/область',
    latitude DECIMAL(10, 8) COMMENT 'Широта',
    longitude DECIMAL(11, 8) COMMENT 'Долгота',
    isp VARCHAR(255) COMMENT 'Провайдер',
    cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME COMMENT 'Срок действия кэша',
    
    INDEX idx_cached_at (cached_at),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Кэш GeoIP данных';
```

## Примеры запросов

### Состояние аккаунта (для API)

```sql
SELECT 
    a.cn,
    a.valid_from,
    a.valid_to,
    a.is_revoked,
    a.has_ccd,
    CASE 
        WHEN a.is_revoked THEN FALSE
        WHEN a.valid_to < NOW() THEN FALSE
        WHEN NOT a.has_ccd THEN FALSE
        ELSE TRUE
    END as can_connect,
    s.id as last_session_id,
    s.status as last_session_status,
    s.connected_at as last_session_connected_at,
    s.disconnected_at as last_session_disconnected_at,
    s.source_ip as last_session_ip,
    s.country as last_session_country,
    s.city as last_session_city
FROM accounts a
LEFT JOIN sessions s ON s.id = (
    SELECT id FROM sessions 
    WHERE account_id = a.id 
    ORDER BY connected_at DESC 
    LIMIT 1
)
WHERE a.cn = 'username';
```

### Активные сессии

```sql
SELECT 
    s.id,
    a.cn as account,
    s.connected_at,
    s.source_ip,
    s.country,
    s.city,
    s.virtual_ip
FROM sessions s
JOIN accounts a ON a.id = s.account_id
WHERE s.status = 'active';
```

### Статистика неудачных попыток

```sql
SELECT 
    failure_type,
    COUNT(*) as count,
    DATE(attempted_at) as date
FROM connection_attempts
WHERE attempted_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY failure_type, DATE(attempted_at)
ORDER BY date DESC, count DESC;
```

## Миграции (Alembic)

Структура для управления миграциями:

```
database/
├── alembic/
│   ├── versions/
│   │   ├── 001_initial_schema.py
│   │   └── 002_add_indexes.py
│   ├── env.py
│   └── script.py.mako
└── alembic.ini
```
