# OpenVPN LogServer

Пассивный мониторинг OpenVPN-сервера: журнал сессий с геолокацией, учёт
сертификатов, CRL и CCD, REST API и веб-интерфейс.

Система **только наблюдает**. Она не управляет VPN, не выдаёт и не отзывает
сертификаты, не вмешивается в аутентификацию клиентов.

## Возможности

- **Журнал сессий** — кто, когда, с какого IP, сколько трафика, страна и город.
- **Учёт сертификатов** — сроки действия, отзыв по CRL, наличие CCD-файла.
  Поддерживается несколько сертификатов на одного пользователя.
- **Обнаружение оборванных сессий** — если сервер упал и отключение не было
  зафиксировано, сессия помечается отдельным статусом, а не висит активной вечно.
- **REST API** под `/api/v1` и веб-интерфейс на Jinja2 + Bootstrap.

## Как это работает

OpenVPN сам вызывает скрипты-хуки при подключении и отключении клиента — они
пишут события в MySQL. Периодический таймер синхронизирует сертификаты, CRL и CCD
и вычищает оборванные сессии, сверяясь со списком живых клиентов через
management-сокет. Веб-приложение только читает из базы.

Почему хуки, а не разбор логов, и какие из этого следуют ограничения —
[docs/architecture.md](docs/architecture.md).

## Требования

- Linux (проверялось на Debian), OpenVPN 2.5+
- Python 3.9+
- MySQL 8.0+

## Быстрый старт

```bash
pip install -r web/requirements.txt -r collector/requirements.txt -r database/requirements.txt

cp config/database.yaml.example config/database.yaml
cp config/auth.yaml.example     config/auth.yaml
cp config/web.yaml.example      config/web.yaml
# заполнить значения; либо задать всё через ENV и не создавать yaml вовсе

alembic -c database/alembic.ini upgrade head
uvicorn web.main:app --reload
```

Подключение хуков к OpenVPN и systemd-юниты — [docs/deployment.md](docs/deployment.md).
Что обязательно должно быть в `server.conf`, иначе данные молча не собираются —
[docs/openvpn-setup.md](docs/openvpn-setup.md).

### Docker-стенд

```bash
cp docker/.env.example docker/.env   # заполнить значения
docker compose -f docker/docker-compose.yml up -d
```

Поднимает MySQL, OpenVPN-сервер и веб-приложение; клиент запускается профилем
`client`. Схему БД накатывает Alembic из web-контейнера.

## Тесты

```bash
pytest                       # юнит + интеграционные, на SQLite
pytest tests/e2e             # требует Docker
pytest database/tests        # требует локальный MySQL
```

Прод работает на MySQL, а тесты — на SQLite, поэтому расхождения по UNSIGNED,
ENUM и внешним ключам локально не ловятся.

## Документация

| Документ | О чём |
|---|---|
| [architecture.md](docs/architecture.md) | компоненты, границы модулей, принятые решения |
| [invariants.md](docs/invariants.md) | расшифровка кодов `I4.5`, `C1.7`, `M1.4` из докстрингов |
| [database.md](docs/database.md) | схема, миграции, расхождение моделей и MySQL-типов |
| [api.md](docs/api.md) | контракт REST API |
| [multi-certificate.md](docs/multi-certificate.md) | несколько сертификатов на пользователя |
| [openvpn-setup.md](docs/openvpn-setup.md) | требования к `server.conf` |
| [deployment.md](docs/deployment.md) | развёртывание и systemd |
| [timezone.md](docs/timezone.md) | как хранится и отображается время |
| [known-gaps.md](docs/known-gaps.md) | что заявлено, но не работает |

Перед изменением кода стоит заглянуть в `invariants.md`: часть требований
неочевидна, а их нарушение ломает VPN или портит журнал. Самый жёсткий пример —
хуки обязаны завершаться с кодом 0 при любой ошибке, иначе OpenVPN откажет
клиенту в подключении.

## Лицензия

MIT
