"""
Модуль для работы с GeoIP с кэшированием.

Предоставляет функции для получения геолокации IP адреса
с использованием внешнего API и кэшированием результатов в БД.

Инварианты:
- I3.1: Модуль не зависит от остальной системы (только от БД)
- I3.2: При cache hit не делается внешний запрос
- I3.3: При cache miss результат сохраняется в БД
- I3.4: При недоступности внешнего API возвращается None (не падает)
- I3.5: Таймаут внешнего запроса не более 5 секунд
"""

import ipaddress
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import GeoIPCache

# Настройка логирования
logger = logging.getLogger(__name__)

# Константы модуля
GEOIP_API_URL = "http://ip-api.com/json/{ip}"
CACHE_TTL_DAYS = 7
REQUEST_TIMEOUT = 5  # I3.5: Таймаут не более 5 секунд


def is_valid_ip(ip: str) -> bool:
    """
    Проверяет валидность IP адреса (IPv4 или IPv6).
    
    Args:
        ip: IP адрес для проверки
    
    Returns:
        True если IP валиден, иначе False
    """
    if not ip or not isinstance(ip, str):
        return False
    
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _get_db_session(db_session: Optional[Session] = None) -> Session:
    """
    Получает сессию БД или создает новую.
    
    Args:
        db_session: Существующая сессия БД (опционально)
    
    Returns:
        Сессия SQLAlchemy
    """
    if db_session is not None:
        return db_session
    return SessionLocal()


def _get_cached_geoip(db: Session, ip: str) -> Optional[GeoIPCache]:
    """
    Получает GeoIP данные из кэша БД.
    
    Args:
        db: Сессия БД
        ip: IP адрес для поиска
    
    Returns:
        GeoIPCache объект если найден и не истек, иначе None
    """
    cache_entry = db.query(GeoIPCache).filter(GeoIPCache.ip == ip).first()
    
    if cache_entry is None:
        return None
    
    # Проверяем, не истек ли срок кэша
    if cache_entry.is_expired():
        # Удаляем устаревшую запись
        db.delete(cache_entry)
        db.commit()
        return None
    
    return cache_entry


def _save_to_cache(db: Session, ip: str, data: dict) -> GeoIPCache:
    """
    Сохраняет GeoIP данные в кэш БД.
    
    Args:
        db: Сессия БД
        ip: IP адрес
        data: Словарь с GeoIP данными
    
    Returns:
        Созданная или обновленная запись кэша
    """
    # Рассчитываем время истечения кэша
    expires_at = datetime.utcnow() + timedelta(days=CACHE_TTL_DAYS)
    
    # Проверяем, есть ли уже запись для этого IP
    cache_entry = db.query(GeoIPCache).filter(GeoIPCache.ip == ip).first()
    
    if cache_entry:
        # Обновляем существующую запись
        cache_entry.country = data.get('country')
        cache_entry.country_code = data.get('country_code')
        cache_entry.city = data.get('city')
        cache_entry.region = data.get('region')
        cache_entry.latitude = data.get('latitude')
        cache_entry.longitude = data.get('longitude')
        cache_entry.isp = data.get('isp')
        cache_entry.cached_at = datetime.utcnow()
        cache_entry.expires_at = expires_at
    else:
        # Создаем новую запись
        cache_entry = GeoIPCache(
            ip=ip,
            country=data.get('country'),
            country_code=data.get('country_code'),
            city=data.get('city'),
            region=data.get('region'),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            isp=data.get('isp'),
            cached_at=datetime.utcnow(),
            expires_at=expires_at
        )
        db.add(cache_entry)
    
    db.commit()
    db.refresh(cache_entry)
    return cache_entry


def _fetch_from_api(ip: str) -> Optional[dict]:
    """
    Запрашивает GeoIP данные из внешнего API.
    
    Args:
        ip: IP адрес для поиска
    
    Returns:
        Словарь с GeoIP данными или None при ошибке
    """
    try:
        url = GEOIP_API_URL.format(ip=ip)
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        # Проверяем статус ответа API
        if data.get('status') != 'success':
            logger.warning(f"GeoIP API returned error for IP {ip}: {data.get('message')}")
            return None
        
        # Преобразуем ответ API в наш формат
        return {
            'country': data.get('country'),
            'country_code': data.get('countryCode'),
            'city': data.get('city'),
            'region': data.get('regionName'),
            'latitude': data.get('lat'),
            'longitude': data.get('lon'),
            'isp': data.get('isp')
        }
    
    except requests.exceptions.Timeout:
        logger.warning(f"GeoIP API timeout for IP {ip}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"GeoIP API request failed for IP {ip}: {e}")
        return None
    except (ValueError, KeyError) as e:
        logger.warning(f"GeoIP API response parsing failed for IP {ip}: {e}")
        return None


def resolve_geoip(ip: str, db_session: Optional[Session] = None) -> dict:
    """
    Получает геолокацию IP адреса с кэшированием.
    
    Сначала проверяет кэш в БД (I3.2), при cache miss делает
    запрос к внешнему API и сохраняет результат в БД (I3.3).
    При любой ошибке возвращает dict с None значениями (I3.4).
    
    Args:
        ip: IP адрес для поиска
        db_session: Сессия БД (опционально, создаётся если не передана)
    
    Returns:
        dict с ключами: country, country_code, city, region,
                        latitude, longitude, isp
        При ошибке или отсутствии данных возвращает dict с None значениями
    """
    # Проверяем валидность IP
    if not is_valid_ip(ip):
        logger.debug(f"Invalid IP address: {ip}")
        return {
            'country': None,
            'country_code': None,
            'city': None,
            'region': None,
            'latitude': None,
            'longitude': None,
            'isp': None
        }
    
    # Определяем, нужно ли нам закрывать сессию
    session_created = db_session is None
    db = _get_db_session(db_session)
    
    try:
        # I3.2: Проверяем кэш перед внешним запросом
        cached = _get_cached_geoip(db, ip)
        if cached:
            logger.debug(f"GeoIP cache hit for IP {ip}")
            return {
                'country': cached.country,
                'country_code': cached.country_code,
                'city': cached.city,
                'region': cached.region,
                'latitude': float(cached.latitude) if cached.latitude is not None else None,
                'longitude': float(cached.longitude) if cached.longitude is not None else None,
                'isp': cached.isp
            }
        
        # I3.3: Cache miss - делаем запрос к API
        logger.debug(f"GeoIP cache miss for IP {ip}, fetching from API")
        api_data = _fetch_from_api(ip)
        
        if api_data is not None:
            # Сохраняем в кэш
            _save_to_cache(db, ip, api_data)
            return api_data
        
        # I3.4: API недоступен или вернул ошибку - возвращаем None значения
        return {
            'country': None,
            'country_code': None,
            'city': None,
            'region': None,
            'latitude': None,
            'longitude': None,
            'isp': None
        }
    
    except Exception as e:
        # I3.4: Любая ошибка - возвращаем None значения, не падаем
        logger.error(f"Unexpected error in resolve_geoip for IP {ip}: {e}")
        return {
            'country': None,
            'country_code': None,
            'city': None,
            'region': None,
            'latitude': None,
            'longitude': None,
            'isp': None
        }
    
    finally:
        # Закрываем сессию только если мы её создали
        if session_created and db is not None:
            db.close()
