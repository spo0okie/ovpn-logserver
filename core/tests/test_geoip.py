"""
Тесты для модуля GeoIP.

Проверяют инварианты I3.1-I3.5:
- I3.1: Модуль не зависит от остальной системы (только от БД)
- I3.2: При cache hit не делается внешний запрос
- I3.3: При cache miss результат сохраняется в БД
- I3.4: При недоступности внешнего API возвращается None (не падает)
- I3.5: Таймаут внешнего запроса не более 5 секунд
"""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
import requests
from requests.exceptions import RequestException, Timeout
from sqlalchemy.orm import Session

from core.geoip import (
    resolve_geoip,
    is_valid_ip,
    _fetch_from_api,
    _get_cached_geoip,
    _save_to_cache,
    REQUEST_TIMEOUT,
    CACHE_TTL_DAYS,
    GEOIP_API_URL
)
from core.models import GeoIPCache


class TestIsValidIP:
    """Тесты для функции is_valid_ip."""
    
    def test_valid_ipv4(self):
        """Проверка валидного IPv4 адреса."""
        assert is_valid_ip("192.168.1.1") is True
        assert is_valid_ip("8.8.8.8") is True
        assert is_valid_ip("255.255.255.255") is True
    
    def test_valid_ipv6(self):
        """Проверка валидного IPv6 адреса."""
        assert is_valid_ip("::1") is True
        assert is_valid_ip("2001:4860:4860::8888") is True
        assert is_valid_ip("fe80::1") is True
    
    def test_invalid_ip(self):
        """Проверка невалидных IP адресов."""
        assert is_valid_ip("not_an_ip") is False
        assert is_valid_ip("256.256.256.256") is False
        assert is_valid_ip("") is False
        assert is_valid_ip(None) is False
        assert is_valid_ip("192.168.1") is False


class TestI31_ModuleIsolation:
    """
    Тест I3.1: Модуль не зависит от остальной системы.
    
    Проверяем, что модуль импортируется без циклических зависимостей
    и зависит только от core.models и core.database.
    """
    
    def test_module_imports(self):
        """Модуль импортируется без ошибок."""
        # Переимпортируем модуль для проверки
        import importlib
        import core.geoip as geoip_module
        
        importlib.reload(geoip_module)
        
        # Проверяем наличие основных функций
        assert hasattr(geoip_module, 'resolve_geoip')
        assert hasattr(geoip_module, 'is_valid_ip')
    
    def test_module_dependencies(self):
        """Модуль зависит только от разрешенных модулей."""
        import core.geoip as geoip_module
        
        # Проверяем импорты внутри модуля
        import inspect
        source = inspect.getsource(geoip_module)
        
        # Разрешенные импорты из проекта
        allowed_imports = [
            'core.database',
            'core.models',
            'GeoIPCache',
            'SessionLocal'
        ]
        
        # Проверяем, что нет импортов из других модулей проекта
        forbidden_patterns = [
            'from collector',
            'from api',
            'from web',
            'import collector',
            'import api',
            'import web'
        ]
        
        for pattern in forbidden_patterns:
            assert pattern not in source, f"Found forbidden import: {pattern}"


class TestI32_CacheHit:
    """
    Тест I3.2: При cache hit не делается внешний запрос.
    
    Предотвращает лишние внешние запросы.
    """
    
    def test_cache_hit_no_external_request(self, db_session: Session, mocker):
        """Cache hit не делает внешний запрос."""
        # Создаем кэш
        future = datetime.utcnow() + timedelta(days=30)
        cache_entry = GeoIPCache(
            ip='1.2.3.4',
            country='Russia',
            country_code='RU',
            city='Moscow',
            region='Moscow',
            latitude=55.7558,
            longitude=37.6173,
            isp='Test ISP',
            cached_at=datetime.utcnow(),
            expires_at=future
        )
        db_session.add(cache_entry)
        db_session.commit()
        
        # Мокаем requests.get
        mock_get = mocker.patch('requests.get')
        
        # Вызываем resolve_geoip
        result = resolve_geoip('1.2.3.4', db_session=db_session)
        
        # Проверяем результат из кэша
        assert result['country'] == 'Russia'
        assert result['country_code'] == 'RU'
        assert result['city'] == 'Moscow'
        
        # Проверяем, что внешний запрос НЕ был сделан
        mock_get.assert_not_called()
    
    def test_cache_hit_returns_correct_data(self, db_session: Session, mocker):
        """Cache hit возвращает корректные данные из БД."""
        future = datetime.utcnow() + timedelta(days=30)
        cache_entry = GeoIPCache(
            ip='8.8.8.8',
            country='United States',
            country_code='US',
            city='Mountain View',
            region='California',
            latitude=37.3860,
            longitude=-122.0838,
            isp='Google LLC',
            cached_at=datetime.utcnow(),
            expires_at=future
        )
        db_session.add(cache_entry)
        db_session.commit()
        
        mocker.patch('requests.get')
        
        result = resolve_geoip('8.8.8.8', db_session=db_session)
        
        assert result['country'] == 'United States'
        assert result['country_code'] == 'US'
        assert result['city'] == 'Mountain View'
        assert result['region'] == 'California'
        assert result['latitude'] == 37.3860
        assert result['longitude'] == -122.0838
        assert result['isp'] == 'Google LLC'


class TestI33_CacheMiss:
    """
    Тест I3.3: При cache miss результат сохраняется в БД.
    
    Предотвращает утечку кэша (не сохранение результатов).
    """
    
    def test_cache_miss_saves_to_db(self, db_session: Session, mocker):
        """При cache miss результат сохраняется в БД."""
        # Мокаем успешный ответ API
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'success',
            'country': 'Germany',
            'countryCode': 'DE',
            'city': 'Berlin',
            'regionName': 'Berlin',
            'lat': 52.5200,
            'lon': 13.4050,
            'isp': 'Test Provider'
        }
        mock_response.raise_for_status.return_value = None
        
        mocker.patch('requests.get', return_value=mock_response)
        
        # Вызываем resolve_geoip (кэша нет)
        result = resolve_geoip('9.9.9.9', db_session=db_session)
        
        # Проверяем результат
        assert result['country'] == 'Germany'
        
        # Проверяем, что данные сохранены в БД
        cache_entry = db_session.query(GeoIPCache).filter(
            GeoIPCache.ip == '9.9.9.9'
        ).first()
        
        assert cache_entry is not None
        assert cache_entry.country == 'Germany'
        assert cache_entry.country_code == 'DE'
        assert cache_entry.city == 'Berlin'
    
    def test_cache_miss_updates_existing(self, db_session: Session, mocker):
        """При cache miss обновляется существующая запись если она есть."""
        # Создаем устаревшую запись
        past = datetime.utcnow() - timedelta(days=1)
        old_cache = GeoIPCache(
            ip='5.5.5.5',
            country='Old Country',
            country_code='OC',
            city='Old City',
            expires_at=past  # Устарело
        )
        db_session.add(old_cache)
        db_session.commit()

        # Мокаем успешный ответ API
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'success',
            'country': 'New Country',
            'countryCode': 'NC',
            'city': 'New City',
            'regionName': 'New Region',
            'lat': 10.0,
            'lon': 20.0,
            'isp': 'New ISP'
        }
        mock_response.raise_for_status.return_value = None

        mocker.patch('requests.get', return_value=mock_response)

        # Вызываем resolve_geoip
        result = resolve_geoip('5.5.5.5', db_session=db_session)

        # Проверяем обновление
        assert result['country'] == 'New Country'

        # Проверяем что в БД обновлено (запросим заново, т.к. старая запись была удалена)
        cache_entry = db_session.query(GeoIPCache).filter(
            GeoIPCache.ip == '5.5.5.5'
        ).first()

        assert cache_entry is not None
        assert cache_entry.country == 'New Country'


class TestI34_ApiUnavailable:
    """
    Тест I3.4: При недоступности внешнего API возвращается None.
    
    Предотвращает падение системы при недоступности GeoIP API.
    """
    
    def test_api_unavailable_returns_none(self, db_session: Session, mocker):
        """API недоступен - возвращаем None значения."""
        mocker.patch('requests.get', side_effect=RequestException("Connection error"))
        
        result = resolve_geoip('1.2.3.4', db_session=db_session)
        
        assert result == {
            'country': None,
            'country_code': None,
            'city': None,
            'region': None,
            'latitude': None,
            'longitude': None,
            'isp': None
        }
    
    def test_api_timeout_returns_none(self, db_session: Session, mocker):
        """API таймаут - возвращаем None значения."""
        mocker.patch('requests.get', side_effect=Timeout("Request timeout"))
        
        result = resolve_geoip('1.2.3.4', db_session=db_session)
        
        assert result['country'] is None
        assert result['city'] is None
    
    def test_api_error_status_returns_none(self, db_session: Session, mocker):
        """API возвращает ошибку в статусе - возвращаем None значения."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'fail',
            'message': 'invalid query'
        }
        mock_response.raise_for_status.return_value = None
        
        mocker.patch('requests.get', return_value=mock_response)
        
        result = resolve_geoip('1.2.3.4', db_session=db_session)
        
        assert result['country'] is None
        assert result['city'] is None
    
    def test_invalid_ip_returns_none(self, db_session: Session, mocker):
        """Невалидный IP - возвращаем None значения без запроса к API."""
        mock_get = mocker.patch('requests.get')
        
        result = resolve_geoip('not_an_ip', db_session=db_session)
        
        assert result['country'] is None
        assert result['city'] is None
        mock_get.assert_not_called()


class TestI35_Timeout:
    """
    Тест I3.5: Таймаут внешнего запроса не более 5 секунд.
    
    Предотвращает зависание скриптов.
    """
    
    def test_request_timeout_constant(self):
        """Проверяем константу таймаута."""
        assert REQUEST_TIMEOUT == 5
        assert REQUEST_TIMEOUT <= 5
    
    def test_request_uses_timeout(self, db_session: Session, mocker):
        """Запрос к API использует таймаут."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'success',
            'country': 'Test',
            'countryCode': 'TT',
            'city': 'Test City',
            'regionName': 'Test Region',
            'lat': 0.0,
            'lon': 0.0,
            'isp': 'Test ISP'
        }
        mock_response.raise_for_status.return_value = None
        
        mock_get = mocker.patch('requests.get', return_value=mock_response)
        
        resolve_geoip('1.2.3.4', db_session=db_session)
        
        # Проверяем что requests.get был вызван с таймаутом
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert 'timeout' in call_kwargs
        assert call_kwargs['timeout'] == 5


class TestFetchFromApi:
    """Тесты для внутренней функции _fetch_from_api."""
    
    def test_successful_fetch(self, mocker):
        """Успешный запрос к API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'success',
            'country': 'France',
            'countryCode': 'FR',
            'city': 'Paris',
            'regionName': 'Île-de-France',
            'lat': 48.8566,
            'lon': 2.3522,
            'isp': 'Orange'
        }
        mock_response.raise_for_status.return_value = None
        
        mocker.patch('requests.get', return_value=mock_response)
        
        result = _fetch_from_api('1.1.1.1')
        
        assert result is not None
        assert result['country'] == 'France'
        assert result['country_code'] == 'FR'
        assert result['city'] == 'Paris'
        assert result['latitude'] == 48.8566
        assert result['longitude'] == 2.3522
    
    def test_fetch_with_timeout(self, mocker):
        """Запрос с таймаутом."""
        mock_get = mocker.patch('requests.get')
        mock_get.return_value.json.return_value = {
            'status': 'success',
            'country': 'Test',
            'countryCode': 'TT',
            'city': 'Test',
            'regionName': 'Test',
            'lat': 0.0,
            'lon': 0.0,
            'isp': 'Test'
        }
        mock_get.return_value.raise_for_status.return_value = None
        
        _fetch_from_api('1.1.1.1')
        
        mock_get.assert_called_once_with(
            GEOIP_API_URL.format(ip='1.1.1.1'),
            timeout=REQUEST_TIMEOUT
        )


class TestCacheOperations:
    """Тесты для операций с кэшем."""
    
    def test_get_cached_geoip_found(self, db_session: Session):
        """Получение существующей записи из кэша."""
        future = datetime.utcnow() + timedelta(days=7)
        cache = GeoIPCache(
            ip='2.2.2.2',
            country='Italy',
            expires_at=future
        )
        db_session.add(cache)
        db_session.commit()
        
        result = _get_cached_geoip(db_session, '2.2.2.2')
        
        assert result is not None
        assert result.country == 'Italy'
    
    def test_get_cached_geoip_not_found(self, db_session: Session):
        """Запись в кэше не найдена."""
        result = _get_cached_geoip(db_session, '3.3.3.3')
        
        assert result is None
    
    def test_get_cached_geoip_expired(self, db_session: Session):
        """Истекшая запись удаляется из кэша."""
        past = datetime.utcnow() - timedelta(days=1)
        cache = GeoIPCache(
            ip='4.4.4.4',
            country='Expired Country',
            expires_at=past
        )
        db_session.add(cache)
        db_session.commit()
        
        result = _get_cached_geoip(db_session, '4.4.4.4')
        
        assert result is None
        
        # Проверяем что запись удалена
        remaining = db_session.query(GeoIPCache).filter(
            GeoIPCache.ip == '4.4.4.4'
        ).first()
        assert remaining is None
    
    def test_save_to_cache_new(self, db_session: Session):
        """Сохранение новой записи в кэш."""
        data = {
            'country': 'Spain',
            'country_code': 'ES',
            'city': 'Madrid',
            'region': 'Madrid',
            'latitude': 40.4168,
            'longitude': -3.7038,
            'isp': 'Telefonica'
        }
        
        result = _save_to_cache(db_session, '6.6.6.6', data)
        
        assert result.ip == '6.6.6.6'
        assert result.country == 'Spain'
        assert result.country_code == 'ES'
        
        # Проверяем что сохранено в БД
        saved = db_session.query(GeoIPCache).filter(
            GeoIPCache.ip == '6.6.6.6'
        ).first()
        assert saved is not None
        assert saved.country == 'Spain'
    
    def test_save_to_cache_update(self, db_session: Session):
        """Обновление существующей записи в кэше."""
        # Создаем начальную запись
        cache = GeoIPCache(
            ip='7.7.7.7',
            country='Old',
            country_code='OL',
            city='Old City',
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        db_session.add(cache)
        db_session.commit()
        
        # Обновляем
        data = {
            'country': 'New',
            'country_code': 'NE',
            'city': 'New City',
            'region': 'New Region',
            'latitude': 1.0,
            'longitude': 2.0,
            'isp': 'New ISP'
        }
        
        result = _save_to_cache(db_session, '7.7.7.7', data)
        
        assert result.country == 'New'
        assert result.country_code == 'NE'
        
        # Проверяем что в БД одна запись
        count = db_session.query(GeoIPCache).filter(
            GeoIPCache.ip == '7.7.7.7'
        ).count()
        assert count == 1


class TestIntegration:
    """Интеграционные тесты полного flow."""
    
    def test_full_flow_cache_miss_then_hit(self, db_session: Session, mocker):
        """Полный flow: cache miss -> API -> cache hit."""
        # Мокаем API
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'success',
            'country': 'Netherlands',
            'countryCode': 'NL',
            'city': 'Amsterdam',
            'regionName': 'North Holland',
            'lat': 52.3676,
            'lon': 4.9041,
            'isp': 'KPN'
        }
        mock_response.raise_for_status.return_value = None
        
        mock_get = mocker.patch('requests.get', return_value=mock_response)
        
        # Первый вызов - cache miss
        result1 = resolve_geoip('10.0.0.1', db_session=db_session)
        assert result1['country'] == 'Netherlands'
        assert mock_get.call_count == 1
        
        # Второй вызов - cache hit
        mock_get.reset_mock()
        result2 = resolve_geoip('10.0.0.1', db_session=db_session)
        assert result2['country'] == 'Netherlands'
        mock_get.assert_not_called()  # Не должно быть запроса к API
    
    def test_session_management(self, db_session: Session, mocker):
        """Управление сессией БД при передаче внешней сессии."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'success',
            'country': 'Belgium',
            'countryCode': 'BE',
            'city': 'Brussels',
            'regionName': 'Brussels',
            'lat': 50.8503,
            'lon': 4.3517,
            'isp': 'Proximus'
        }
        mock_response.raise_for_status.return_value = None
        
        mocker.patch('requests.get', return_value=mock_response)
        
        # Передаем внешнюю сессию
        result = resolve_geoip('11.0.0.1', db_session=db_session)
        
        assert result['country'] == 'Belgium'
        
        # Проверяем что запись в той же сессии
        cache = db_session.query(GeoIPCache).filter(
            GeoIPCache.ip == '11.0.0.1'
        ).first()
        assert cache is not None
