"""
Единая точка получения времени.

Канон хранения — **naive UTC** (docs/timezone.md): в БД лежит время без
tzinfo, конвертация в локальную зону происходит только на границе отображения.

Зачем отдельный модуль, а не `datetime.utcnow()`:

- `datetime.utcnow()` объявлен устаревшим с Python 3.12 и будет удалён;
- прямая замена на `datetime.now(timezone.utc)` даёт **aware**-время, а его
  сравнение с naive-значениями из БД кидает `TypeError`. Именно так в проекте
  и появилось смешение стилей;
- функция ниже возвращает ровно то же, что возвращал `utcnow()`, но без
  устаревшего вызова.

Исключение — файловые сессии в `web/auth.py`: они не касаются БД, полностью
самодостаточны и работают с aware-временем. Смешения не возникает, поэтому их
переводить не нужно.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Текущее время UTC без tzinfo (naive) — для записи в БД и сравнений с ней."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcfromtimestamp(timestamp) -> datetime:
    """Unix timestamp -> naive UTC. Замена устаревшему datetime.utcfromtimestamp."""
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
