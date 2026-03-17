"""
Утилиты для работы с часовыми поясами.

Автоматически определяет локальный часовой пояс сервера
и конвертирует UTC datetime в локальное время.
"""

from datetime import datetime, timezone

import tzlocal


def get_local_tz():
    """
    Получает локальный часовой пояс сервера.
    
    Использует tzlocal для автоматического определения системного часового пояса.
    
    Returns:
        zoneinfo.ZoneInfo: Локальный часовой пояс
    """
    return tzlocal.get_localzone()


def format_datetime(utc_dt, fmt='%Y-%m-%d %H:%M'):
    """
    Форматирует UTC datetime в локальное время.
    
    Автоматически определяет локальный часовой пояс сервера
    и конвертирует UTC время для отображения.
    
    Args:
        utc_dt: datetime объект или ISO строка (UTC время)
        fmt: Формат вывода (по умолчанию 'ГГГГ-ММ-ДД чч:мм')
    
    Returns:
        str: Отформатированная строка времени в локальном часовом поясе
    
    Examples:
        >>> from datetime import datetime, timezone
        >>> utc = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        >>> format_datetime(utc)
        '2024-01-15 13:30'  # Если сервер в UTC+3
    """
    # Если передана строка, парсим её
    if isinstance(utc_dt, str):
        # Обрабатываем ISO строку (может содержать Z или +00:00)
        if utc_dt.endswith('Z'):
            utc_dt = utc_dt[:-1] + '+00:00'
        try:
            utc_dt = datetime.fromisoformat(utc_dt)
        except ValueError:
            # Если не удалось распарсить, возвращаем как есть
            return utc_dt
    
    local_tz = get_local_tz()
    
    # Делаем UTC aware если datetime naive
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    
    # Конвертируем в локальное время
    local_dt = utc_dt.astimezone(local_tz)
    
    return local_dt.strftime(fmt)
