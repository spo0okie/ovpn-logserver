# План: Отображение времени в локальном часовом поясе

## Цель
Отображать время в WEB UI в локальном часовом поясе сервера (системный часовой пояс) вместо UTC, формат: `ГГГГ-ММ-ДД чч:мм`

## Текущее состояние
- Время хранится в UTC в базе данных
- В [`pages.py`](web/routes/pages.py:194) используется `datetime.utcnow()` для переменной `now`
- В шаблонах datetime объекты форматируются через `strftime('%Y-%m-%d %H:%M')` - это время интерпретатора Python

## Решение

### Шаг 1: Создать утилиту для работы с часовыми поясами
**Файл:** `web/utils/timezone.py`

Создать модуль с автоматическим определением системного часового пояса и конвертацией UTC в локальное время.

### Шаг 2: Добавить Jinja2 фильтр для форматирования времени
**Файл:** `web/routes/pages.py`

Зарегистрировать в Jinja2 шаблонизаторе фильтр `local_datetime` для автоматической конвертации UTC → локальное время.

### Шаг 3: Обновить переменную `now` в контроллерах
**Файл:** `web/routes/pages.py`

Заменить `datetime.utcnow()` на `datetime.now(local_tz)` для консистентности.

### Шаг 4: Обновить все шаблоны для использования фильтра
- `web/templates/sessions.html` - connected_at, disconnected_at
- `web/templates/accounts.html` - created_at
- `web/templates/account_detail.html` - created_at, updated_at, valid_from/to, revoked_at, connected_at, disconnected_at
- `web/templates/attempts.html` - attempted_at

## Детали реализации

### Зависимости
Добавить `tzlocal` в `web/requirements.txt`:
```
tzlocal>=5.2
```

### Реализация timezone.py
```python
# web/utils/timezone.py
from datetime import datetime, timezone
import tzlocal  # Автоматическое определение системного часового пояса

def get_local_tz():
    """Получает локальный часовой пояс сервера."""
    return tzlocal.get_localzone()

def format_datetime(utc_dt, fmt='%Y-%m-%d %H:%M'):
    """Форматирует UTC datetime в локальное время, формат ГГГГ-ММ-ДД чч:мм."""
    if isinstance(utc_dt, str):
        # Парсим ISO строку (может содержать Z или +00:00)
        if utc_dt.endswith('Z'):
            utc_dt = utc_dt[:-1] + '+00:00'
        utc_dt = datetime.fromisoformat(utc_dt)
    
    local_tz = get_local_tz()
    # Делаем UTC aware если naive
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    
    local_dt = utc_dt.astimezone(local_tz)
    return local_dt.strftime(fmt)
```
