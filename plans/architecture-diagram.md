# Архитектурная диаграмма системы

## Общая архитектура

```mermaid
flowchart TB
    subgraph "OpenVPN Server"
        OV[OpenVPN Process]
        CERT[/etc/openvpn/clients/]
        CCD[/etc/openvpn/ccd/]
        CRL[/etc/openvpn/crl.pem/]
        LOG[/var/log/openvpn/server.log/]
    end

    subgraph "OpenVPN LogServer"
        direction TB
        
        subgraph "Connection Scripts"
            CONN[client-connect.py]
            DISC[client-disconnect.py]
        end
        
        subgraph "Background Tasks"
            CS[cert_sync.py<br/>cron]
            CC[crl_checker.py<br/>cron]
            CD[ccd_checker.py<br/>cron]
            EW[error_watcher.py<br/>daemon]
        end
        
        subgraph "Shared Modules"
            GR[geoip_resolver.py]
        end
        
        subgraph "Web Application"
            API[REST API<br/>FastAPI]
            UI[Web UI<br/>Jinja2 + Bootstrap]
            AUTH[Basic Auth]
        end
        
        subgraph "Database Layer"
            DB[(MySQL)]
            ACC[(accounts)]
            SES[(sessions)]
            ATT[(connection_attempts)]
            GEO[(geoip_cache)]
        end
    end

    subgraph "External Services"
        GEOAPI[GeoIP API<br/>ip-api.com]
    end

    subgraph "Users"
        ADMIN[Administrator]
    end

    %% Data flows - Connection/Disconnection
    OV -->|calls| CONN
    OV -->|calls| DISC
    OV -->|writes| LOG
    
    CONN -->|INSERT| SES
    DISC -->|UPDATE| SES
    CONN -->|queries| GR
    GR -->|caches| GEO
    GR -.->|requests| GEOAPI
    
    %% Background tasks
    CERT -->|scans| CS
    CRL -->|parses| CC
    CCD -->|checks| CD
    LOG -->|reads| EW
    
    CS -->|writes| ACC
    CC -->|updates| ACC
    CD -->|updates| ACC
    EW -->|writes| ATT
    
    %% Web
    ACC -->|reads| API
    SES -->|reads| API
    ATT -->|reads| API
    GEO -->|reads| API
    
    API -->|serves| UI
    AUTH -->|protects| API
    AUTH -->|protects| UI
    
    ADMIN -->|accesses| UI
    ADMIN -.->|API calls| API
```

## Поток данных

```mermaid
sequenceDiagram
    participant OV as OpenVPN
    participant LOG as Log File
    participant LW as Log Watcher
    participant GR as GeoIP Resolver
    participant DB as MySQL
    participant API as REST API
    participant UI as Web UI
    participant USER as User

    %% Session start
    OV->>LOG: Write connection event
    LW->>LOG: Read new line
    LW->>LW: Parse event (CN, IP, time)
    LW->>GR: Resolve IP location
    GR->>DB: Check cache
    alt Cache miss
        GR->>GR: Call external API
        GR->>DB: Store in cache
    end
    GR-->>LW: Return geo data
    LW->>DB: INSERT INTO sessions

    %% Session end
    OV->>LOG: Write disconnect event
    LW->>LOG: Read new line
    LW->>DB: UPDATE sessions SET disconnected_at

    %% User views data
    USER->>UI: Open dashboard
    UI->>API: GET /api/v1/stats/overview
    API->>DB: SELECT count, stats
    DB-->>API: Return data
    API-->>UI: JSON response
    UI-->>USER: Render dashboard

    %% User views sessions
    USER->>UI: Click Sessions
    UI->>API: GET /api/v1/sessions
    API->>DB: SELECT with pagination
    DB-->>API: Return sessions
    API-->>UI: JSON response
    UI-->>USER: Render table
```

## Компоненты Data Collector

```mermaid
flowchart LR
    subgraph "OpenVPN Events"
        CONN[client-connect]
        DISC[client-disconnect]
        LOG[/OpenVPN Log/]
    end

    subgraph "Scripts"
        CS[client-connect.py]
        DS[client-disconnect.py]
        EW[error_watcher.py]
    end

    subgraph "Background Tasks"
        SYNC[Sync Scripts<br/>periodic]
    end

    subgraph "Processing"
        GEO[GeoIP Resolver<br/>+ cache]
        SSL[OpenSSL Parser]
        CRLP[CRL Parser]
    end

    subgraph "Output"
        DB[(MySQL Database)]
    end

    CONN -->|env vars| CS
    DISC -->|env vars| DS
    LOG -->|errors| EW
    
    CS -->|IP| GEO
    GEO -->|location| CS
    CS -->|INSERT| DB
    DS -->|UPDATE| DB
    EW -->|INSERT| DB

    CERT[/Certificates/] --> SYNC
    CRL[/CRL File/] --> SYNC
    CCD[/CCD Dir/] --> SYNC
    SYNC --> SSL
    SYNC --> CRLP
    SSL -->|cert info| DB
    CRLP -->|revoked status| DB
    SYNC -->|ccd status| DB
```

## Структура базы данных

```mermaid
erDiagram
    ACCOUNTS ||--o{ SESSIONS : has
    ACCOUNTS ||--o{ CONNECTION_ATTEMPTS : has
    SESSIONS ||--o{ GEOIP_CACHE : references
    CONNECTION_ATTEMPTS ||--o{ GEOIP_CACHE : references

    ACCOUNTS {
        int id PK
        string cn UK
        datetime valid_from
        datetime valid_to
        boolean is_revoked
        datetime revoked_at
        boolean has_ccd
        datetime ccd_updated_at
        datetime created_at
        datetime updated_at
    }

    SESSIONS {
        bigint id PK
        int account_id FK
        string session_id
        datetime connected_at
        datetime disconnected_at
        string source_ip
        string country
        string city
        bigint bytes_sent
        bigint bytes_received
        string virtual_ip
        enum status
        datetime created_at
        datetime updated_at
    }

    CONNECTION_ATTEMPTS {
        bigint id PK
        int account_id FK
        datetime attempted_at
        string source_ip
        string cert_cn
        string failure_reason
        enum failure_type
        text details
        datetime created_at
    }

    GEOIP_CACHE {
        string ip PK
        string country
        string country_code
        string city
        string region
        decimal latitude
        decimal longitude
        string isp
        datetime cached_at
        datetime expires_at
    }
```

## Web Application Architecture

```mermaid
flowchart TB
    subgraph "Client"
        BROWSER[Web Browser]
    end

    subgraph "Server"
        direction TB
        
        subgraph "Nginx"
            NGINX[Nginx<br/>Reverse Proxy]
            AUTH[Basic Auth]
        end
        
        subgraph "FastAPI Application"
            ROUTER[Router]
            
            subgraph "API Routes"
                ACC_API[/api/v1/accounts/]
                SES_API[/api/v1/sessions/]
                ATT_API[/api/v1/attempts/]
                STA_API[/api/v1/stats/]
            end
            
            subgraph "Web Routes"
                DASH[/dashboard/]
                ACC_WEB[/accounts/]
                SES_WEB[/sessions/]
                ATT_WEB[/attempts/]
            end
            
            subgraph "Components"
                DEP[Dependencies<br/>DB Session]
                SCH[Schemas<br/>Pydantic]
                MOD[Models<br/>SQLAlchemy]
            end
        end
        
        subgraph "Templates"
            JIN[Jinja2 Templates]
            BOOT[Bootstrap 5]
            DT[DataTables]
            CH[Chart.js]
        end
        
        subgraph "Database"
            DB[(MySQL)]
        end
    end

    BROWSER -->|HTTPS| NGINX
    NGINX --> AUTH
    AUTH -->|proxy_pass| ROUTER
    
    ROUTER --> ACC_API
    ROUTER --> SES_API
    ROUTER --> ATT_API
    ROUTER --> STA_API
    ROUTER --> DASH
    ROUTER --> ACC_WEB
    ROUTER --> SES_WEB
    ROUTER --> ATT_WEB
    
    ACC_API --> DEP
    SES_API --> DEP
    ATT_API --> DEP
    STA_API --> DEP
    
    DASH --> JIN
    ACC_WEB --> JIN
    SES_WEB --> JIN
    ATT_WEB --> JIN
    
    JIN --> BOOT
    JIN --> DT
    JIN --> CH
    
    DEP --> MOD
    MOD --> DB
    
    ACC_API -.->|JSON| BROWSER
    JIN -.->|HTML| BROWSER
```

## Deployment Architecture

```mermaid
flowchart TB
    subgraph "Debian Server"
        direction TB
        
        subgraph "Systemd Services"
            SVC_COL[openvpn-collector.service]
            SVC_WEB[openvpn-web.service]
            SVC_SYNC[openvpn-sync.timer/service]
        end
        
        subgraph "File System"
            OPT[/opt/openvpn-logserver/]
            ETC[/etc/openvpn-logserver/]
            LOGS[/var/log/openvpn-logserver/]
        end
        
        subgraph "OpenVPN Files"
            OVPN_LOG[/var/log/openvpn/]
            OVPN_ETC[/etc/openvpn/]
        end
        
        subgraph "Database"
            MYSQL[(MySQL Server)]
        end
    end

    subgraph "Network"
        NGINX[Nginx :443]
        USERS[Administrators]
    end

    SVC_COL -->|reads| OVPN_LOG
    SVC_COL -->|reads| OVPN_ETC
    SVC_COL -->|writes| MYSQL
    SVC_SYNC -->|reads| OVPN_ETC
    SVC_SYNC -->|writes| MYSQL
    
    SVC_WEB -->|reads| MYSQL
    SVC_WEB -->|serves| NGINX
    NGINX -->|HTTPS| USERS
    
    OPT -->|contains| SVC_COL
    OPT -->|contains| SVC_WEB
    ETC -->|config| SVC_COL
    ETC -->|config| SVC_WEB
    LOGS -->|logs| SVC_COL
    LOGS -->|logs| SVC_WEB
```

## Процесс обработки события подключения

```mermaid
flowchart TD
    A[Клиент подключается к OpenVPN] --> B[OpenVPN вызывает client-connect]
    B --> C[Скрипт получает переменные окружения]
    C --> D[Извлекает CN, IP, VPN IP]
    D --> E[Запросить GeoIP]
    E --> F{В кэше?}
    F -->|Да| G[Взять из БД]
    F -->|Нет| H[Запросить внешний API]
    H --> I[Сохранить в кэш]
    I --> G
    G --> J[INSERT INTO sessions]
    J --> K[Скрипт возвращает exit 0]
    K --> L[OpenVPN продолжает подключение]
```

## Процесс обработки отключения

```mermaid
flowchart TD
    A[Клиент отключается] --> B[OpenVPN вызывает client-disconnect]
    B --> C[Скрипт получает CN, bytes_sent, bytes_received]
    C --> D[UPDATE sessions SET disconnected_at, status='closed']
    D --> E[Скрипт возвращает exit 0]
    E --> F[Сессия завершена]
```
