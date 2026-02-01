# OpenVPN LogServer - Проектная документация

## Обзор

OpenVPN LogServer - это система мониторинга и журналирования сессий OpenVPN, предоставляющая:
- Журналирование всех VPN сессий с геолокацией
- Учет активных сертификатов и их статусов
- Web-интерфейс для просмотра данных
- REST API для интеграции

## Архитектура

Система состоит из трех основных компонентов:

1. **Data Collector** (Python) - сбор и обработка данных
2. **Web Application** (FastAPI) - UI и REST API
3. **Database** (MySQL) - хранение данных

## Структура проекта

```
plans/
├── README.md                 # Этот файл - обзор проекта
├── project-structure.md      # Структура директорий и компоненты
├── database-schema.md        # Схема MySQL БД
├── collector-design.md       # Архитектура модуля сбора данных
├── api-design.md            # REST API endpoints
├── web-ui-design.md         # Дизайн Web UI
├── openvpn-config.md        # Требуемая конфигурация OpenVPN
├── deployment.md            # Развертывание и systemd
└── architecture-diagram.md  # Диаграммы архитектуры
```

## Быстрый старт

### Требования

- Debian/Ubuntu Linux
- OpenVPN 2.5+
- Python 3.9+
- MySQL 8.0+
- 512 MB RAM минимум
- 10 GB дискового пространства

### Установка

1. **Подготовка OpenVPN** (см. [openvpn-config.md](openvpn-config.md))
   - Настроить логирование
   - Включить management interface
   - Создать структуру директорий

2. **Установка компонентов** (см. [deployment.md](deployment.md))
   ```bash
   # Создать пользователя
   sudo useradd -r -s /bin/false ovpn-logserver
   
   # Установить зависимости
   sudo apt install python3 python3-venv mysql-server
   
   # Настроить БД
   mysql -u root -p < database/init.sql
   ```

3. **Запуск сервисов**
   ```bash
   sudo systemctl enable --now openvpn-collector
   sudo systemctl enable --now openvpn-web
   sudo systemctl enable --now openvpn-sync.timer
   ```

## Функциональность

### Журнал сессий

- Учетная запись (CN сертификата)
- Время начала и окончания сессии
- IP адрес с геолокацией (страна/город)
- Объем переданных данных

### Список сертификатов

- Сроки действия
- Признак отзыва (CRL)
- Признак наличия CCD файла
- Статус возможности подключения

### REST API

- `GET /api/v1/accounts` - список аккаунтов
- `GET /api/v1/accounts/{cn}/status` - состояние аккаунта
- `GET /api/v1/sessions` - журнал сессий
- `GET /api/v1/sessions/{id}` - детали сессии
- `GET /api/v1/attempts` - неудачные попытки
- `GET /api/v1/stats/*` - статистика

Подробнее в [api-design.md](api-design.md)

### Web UI

- Dashboard с обзором метрик
- Таблица аккаунтов с фильтрами
- Журнал сессий с поиском
- Статистика и графики

Подробнее в [web-ui-design.md](web-ui-design.md)

## Технологический стек

### Data Collector
- **Язык:** Python 3.9+
- **Библиотеки:** 
  - `watchdog` - мониторинг файлов
  - `sqlalchemy` - работа с БД
  - `cryptography` - парсинг CRL
  - `pyopenssl` - работа с сертификатами
  - `requests` - GeoIP API

### Web Application
- **Фреймворк:** FastAPI
- **Шаблонизатор:** Jinja2
- **ORM:** SQLAlchemy
- **Frontend:** Bootstrap 5, DataTables, Chart.js

### Database
- **СУБД:** MySQL 8.0
- **Миграции:** Alembic

## Безопасность

- Basic аутентификация для Web и API
- Изоляция прав доступа (отдельный пользователь)
- Только чтение OpenVPN файлов
- Параметризованные SQL запросы
- Валидация входных данных (Pydantic)

## Мониторинг

```bash
# Статус сервисов
sudo systemctl status openvpn-collector openvpn-web

# Логи
sudo journalctl -u openvpn-collector -f
sudo tail -f /opt/openvpn-logserver/logs/web.log

# Health check
curl -u admin:password http://localhost:8000/api/v1/stats/overview
```

## Резервное копирование

```bash
# База данных
mysqldump -u root -p openvpn_logs > backup.sql

# Конфигурация
cp -r /etc/openvpn-logserver /backup/
```

## Развитие проекта

### Возможные улучшения

1. **Real-time обновления** - WebSocket для live-данных
2. **Уведомления** - алерты на email/Telegram
3. **Графики** - детальная аналитика
4. **Экспорт** - PDF отчеты
5. **Роли** - разграничение доступа
6. **2FA** - двухфакторная аутентификация

## Лицензия

MIT License

## Поддержка

При возникновении проблем:
1. Проверить логи сервисов
2. Проверить права доступа к файлам
3. Проверить подключение к БД
4. Обратиться к документации в папке `plans/`
