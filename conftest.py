"""
Корневой conftest: тестовое окружение выставляется ДО импорта любых модулей
проекта.

Зачем: `core/database.py` создаёт engine и SessionLocal на этапе импорта, а
`core/config.py` кеширует конфиг через lru_cache. Если какой-нибудь conftest
импортирует `core.database` раньше, чем выставлен DATABASE_URL, движок
закрепляется на боевой MySQL из config/database.yaml — и последующие тесты
(например web/tests) идут в прод-конфиг вместо SQLite. Из-за этого набор
тестов зависел от порядка запуска: по отдельности пакеты проходили, а вместе
падали с "Access denied for user".

pytest импортирует корневой conftest.py раньше всех тестовых модулей и прочих
conftest'ов, поэтому здесь безопасное место для дефолтов окружения.

Индивидуальные conftest'ы могут переопределить DATABASE_URL под себя
(web/tests так и делает) — важно лишь, чтобы к моменту первого импорта
core.database значение уже не указывало на боевую БД.
"""

import os

# Тестовая БД по умолчанию (файловая SQLite в каталоге тестовых артефактов).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_default.db")

# Тестовые креды web-аутентификации, чтобы не читать config/auth.yaml.
os.environ.setdefault("WEB_AUTH_USERNAME", "admin")
os.environ.setdefault("WEB_AUTH_PASSWORD", "admin_password_123")
