"""
Тесты web/utils/timezone.py и предформатированного локального времени в API.

Контракт: в БД всё хранится в naive UTC, конвертация — только на границе
отображения (docs/timezone.md).
"""

from datetime import datetime, timedelta, timezone

import pytest

from web.utils.timezone import format_datetime, get_local_tz


class TestFormatDatetime:
    """Поведение форматирования."""

    def test_naive_datetime_treated_as_utc(self):
        """
        Naive datetime трактуется как UTC — это связующее звено с naive-хранением.
        """
        naive = datetime(2026, 1, 15, 10, 30, 0)
        aware = naive.replace(tzinfo=timezone.utc)
        assert format_datetime(naive) == format_datetime(aware)

    def test_converts_to_server_timezone(self):
        """Результат соответствует переводу UTC в зону сервера."""
        utc = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        expected = utc.astimezone(get_local_tz()).strftime('%Y-%m-%d %H:%M')
        assert format_datetime(utc) == expected

    def test_accepts_iso_string(self):
        """
        Функция принимает и строку: шаблоны получают данные и из ORM (datetime),
        и из pydantic-схем (строка).
        """
        utc = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert format_datetime(utc.isoformat()) == format_datetime(utc)

    def test_accepts_z_suffix(self):
        """ISO-строка с Z вместо +00:00."""
        assert format_datetime('2026-01-15T10:30:00Z') == format_datetime(
            datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        )

    def test_unparsable_string_returned_as_is(self):
        """Нераспознанная строка возвращается без изменений, без исключения."""
        assert format_datetime('не дата') == 'не дата'

    def test_custom_format(self):
        utc = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert len(format_datetime(utc, '%Y')) == 4

    def test_none_raises(self):
        """
        Ограничение: None не поддерживается — вызовы обязаны быть под {% if %}.
        Тест фиксирует это как известное поведение, а не как желаемое.
        """
        with pytest.raises(AttributeError):
            format_datetime(None)


class TestSessionsApiLocalTime:
    """
    Страница /sessions рендерится клиентским DataTables, куда Jinja-фильтр не
    достаёт, поэтому API отдаёт готовые строки локального времени.
    """

    def test_list_contains_local_time(self, client, sample_sessions, auth_headers):
        response = client.get("/api/v1/sessions", headers=auth_headers)
        assert response.status_code == 200

        item = response.json()["data"][0]
        assert "connected_at_local" in item
        assert item["connected_at_local"] == format_datetime(item["connected_at"])

    def test_local_time_differs_from_utc_when_offset(self, client, sample_sessions, auth_headers):
        """
        При ненулевом смещении сервера локальная строка не совпадает с сырым UTC.
        На UTC-сервере проверка вырождается — тогда просто пропускаем.
        """
        if get_local_tz().utcoffset(datetime.now()) == timedelta(0):
            pytest.skip("сервер в UTC, расхождения не будет")

        item = client.get("/api/v1/sessions", headers=auth_headers).json()["data"][0]
        assert item["connected_at_local"] != item["connected_at"]

    def test_closed_session_has_disconnected_local(self, client, sample_sessions, auth_headers):
        items = client.get("/api/v1/sessions", headers=auth_headers).json()["data"]
        closed = [i for i in items if i["disconnected_at"]]
        assert closed, "в фикстуре должна быть закрытая сессия"
        assert closed[0]["disconnected_at_local"] == format_datetime(closed[0]["disconnected_at"])

    def test_active_session_has_no_disconnected_local(self, client, sample_sessions, auth_headers):
        items = client.get("/api/v1/sessions", headers=auth_headers).json()["data"]
        active = [i for i in items if not i["disconnected_at"]]
        assert active, "в фикстуре должна быть активная сессия"
        assert active[0]["disconnected_at_local"] is None
