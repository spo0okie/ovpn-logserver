# План: Стабильная Docker песочница с OpenVPN

## Проблемы текущей конфигурации

1. **OpenVPN контейнер перезапускается (exit code 1)**:
   - Конфликт параметров `--dev tun0` и `--server` в entrypoint.sh с server.conf
   - Отсутствует маппинг `/dev/net/tun` устройства
   - Неправильные capabilities

2. **DH параметры генерация >2 минут**:
   - Уже исправлено использованием ECDH (prime256v1)

3. **tun устройство не создается**:
   - Неправильный entrypoint
   - Отсутствует `--privileged` или корректные capabilities

## Анализ collector скриптов

### Требования collector скриптов:
- **client_connect.py**: Требует `DATABASE_URL`, логирует в `/var/log/openvpn-logserver/`
- **client_disconnect.py**: Требует `DATABASE_URL`
- **session_cleanup.py**: Использует `mgmt_client.py` для получения списка клиентов
- **mgmt_client.py**: Читает сокет из `OPENVPN_MGMT_SOCKET` или `OPENVPN_DIR`

### Management Interface:
- Путь сокета: `/run/openvpn/mgmt.sock` или `/run/openvpn/management.sock`
- Команда: `status 3` для получения списка клиентов

## Решения

### 1. docker-compose.yml

**Изменения:**
- Добавить `privileged: true` для полного доступа к устройствам
- Добавить маппинг `/dev/net/tun:/dev/net/tun`
- Убедиться что `openvpn_mgmt` volume монтируется как tmpfs или bind mount
- Исправить healthcheck

### 2. Dockerfile

**Изменения:**
- Добавить `netcat-openbsd` для wait_for_mysql
- Убедиться что все Python зависимости установлены

### 3. entrypoint.sh

**Изменения:**
- Убрать конфликтующие `--dev tun0` и `--server` параметры (они переопределяют server.conf)
- Добавить создание `/dev/net/tun` если не существует
- Улучшить error handling (не использовать `set -e` критичных секциях)
- Обеспечить правильную последовательность запуска

### 4. server.conf

**Изменения:**
- Установить `management /run/openvpn/mgmt.sock` (стандартный путь)
- Убедиться что `dev tun` (без номера) для автоматического создания
- Настроить правильные пути для всех файлов

## Архитектура решения

```mermaid
flowchart TB
    subgraph Docker Host
        TUN[/dev/net/tun]
        subgraph Docker Network
            OVPN[OpenVPN Server]
            MYSQL[MySQL Database]
            WEB[Web Application]
            
            subgraph OpenVPN Container
                PKI[/etc/openvpn/pki]
                CCD[/etc/openvpn/ccd]
                MGMT[/run/openvpn/mgmt.sock]
                SCRIPTS[Collector Scripts]
            end
        end
    end
    
    CLIENT[OpenVPN Client] -->|UDP 1194| OVPN
    OVPN -->|Unix Socket| MGMT
    SCRIPTS -->|Read Status| MGMT
    SCRIPTS -->|SQL| MYSQL
```

## Инварианты для проверки

- [ ] Docker Compose поднимает все сервисы без перезапусков
- [ ] OpenVPN сервер запущен и принимает соединения
- [ ] Management Interface доступен по пути `/run/openvpn/mgmt.sock`
- [ ] Collector скрипты работают корректно
- [ ] PKI генерируется при первом запуске (менее 30 секунд)
- [ ] Клиент может подключиться к серверу
- [ ] При подключении создается запись в БД
- [ ] При отключении сессия закрывается
