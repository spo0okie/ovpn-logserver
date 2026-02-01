"""
Скрипт проверки CRL (Certificate Revocation List).

Обновляет is_revoked и revoked_at в БД на основе данных из CRL.

Инварианты:
- I6.2: Обновляет is_revoked, revoked_at из CRL
- I6.4: Идемпотентен (повторный запуск не ломает данные)
- I6.5: Только UPDATE операции, никаких INSERT для accounts
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID

from core.database import SessionLocal
from core.models import Account
from collector.config import CRL_FILE, CERTS_DIR, CERT_EXTENSION


def parse_crl(crl_path: str) -> dict:
    """
    Парсит CRL файл и возвращает информацию об отозванных сертификатах.
    
    Args:
        crl_path: Путь к CRL файлу в формате PEM
    
    Returns:
        dict: Словарь с информацией:
            - revoked_certs: dict {serial_number: revocation_date}
            - last_update: datetime последнего обновления CRL
            - next_update: datetime следующего обновления CRL
            - None если не удалось распарсить
    """
    try:
        with open(crl_path, 'rb') as f:
            crl_data = f.read()
        
        # Парсим CRL
        crl = x509.load_pem_x509_crl(crl_data, default_backend())
        
        # Собираем информацию об отозванных сертификатах
        revoked_certs = {}
        for revoked_cert in crl:
            serial = str(revoked_cert.serial_number)
            # Берем дату отзыва если есть, иначе текущее время
            revoked_at = revoked_cert.revocation_date_utc
            if revoked_at is None:
                revoked_at = datetime.utcnow()
            revoked_certs[serial] = revoked_at
        
        return {
            'revoked_certs': revoked_certs,
            'last_update': crl.last_update_utc,
            'next_update': crl.next_update_utc,
        }
    except Exception as e:
        print(f"Error parsing CRL {crl_path}: {e}", file=sys.stderr)
        return None


def extract_cert_info(cert_path: str) -> dict:
    """
    Извлекает информацию из сертификата.
    
    Args:
        cert_path: Путь к файлу сертификата
    
    Returns:
        dict: Словарь с полями cn и serial_number, или None при ошибке
    """
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()
        
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        
        # Извлекаем CN из Subject
        cn = None
        for attr in cert.subject:
            if attr.oid == NameOID.COMMON_NAME:
                cn = attr.value
                break
        
        return {
            'cn': cn,
            'serial_number': str(cert.serial_number)
        }
    except Exception:
        return None


def build_cn_to_serial_map(certs_dir: str) -> dict:
    """
    Строит маппинг CN -> serial_number из директории с сертификатами.
    
    Args:
        certs_dir: Путь к директории с сертификатами
    
    Returns:
        dict: Маппинг {cn: serial_number}
    """
    certs_path = Path(certs_dir)
    if not certs_path.exists() or not certs_path.is_dir():
        return {}
    
    cn_to_serial = {}
    
    # Ищем файлы с расширением сертификатов
    for cert_file in certs_path.glob(f"*{CERT_EXTENSION}"):
        cert_info = extract_cert_info(str(cert_file))
        if cert_info and cert_info['cn']:
            cn_to_serial[cert_info['cn']] = cert_info['serial_number']
    
    return cn_to_serial


def extract_serial_from_cert(cert_path: str) -> str:
    """
    Извлекает серийный номер из сертификата.
    
    Args:
        cert_path: Путь к файлу сертификата
    
    Returns:
        str: Серийный номер сертификата или None
    """
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()
        
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        return str(cert.serial_number)
    except Exception:
        return None


def check_crl(db=None, crl_path: str = None, certs_dir: str = None) -> dict:
    """
    Проверяет CRL и обновляет статус отзыва в БД.
    
    Читает CRL файл и обновляет is_revoked=True, revoked_at для отозванных.
    Сбрасывает is_revoked=False для неотозванных.
    
    Args:
        db: Сессия базы данных (если None, создается новая)
        crl_path: Путь к CRL файлу (если None, используется CRL_FILE)
        certs_dir: Директория с сертификатами (если None, используется CERTS_DIR)
    
    Returns:
        dict: Статистика проверки:
            - checked: количество проверенных записей
            - revoked: количество отозванных
            - unrevoked: количество восстановленных (больше не в CRL)
            - errors: количество ошибок
    
    Invariants: I6.2, I6.4, I6.5
    """
    stats = {
        'checked': 0,
        'revoked': 0,
        'unrevoked': 0,
        'errors': 0,
    }
    
    # Используем переданный путь или дефолтный
    target_crl_path = crl_path or CRL_FILE
    target_certs_dir = certs_dir or CERTS_DIR
    
    # Проверяем существование CRL файла
    if not Path(target_crl_path).exists():
        print(f"CRL file not found: {target_crl_path}", file=sys.stderr)
        stats['errors'] += 1
        return stats
    
    # Парсим CRL
    crl_info = parse_crl(target_crl_path)
    if crl_info is None:
        stats['errors'] += 1
        return stats
    
    revoked_serials = crl_info['revoked_certs']
    
    # Строим маппинг CN -> serial_number из сертификатов
    cn_to_serial = build_cn_to_serial_map(target_certs_dir)
    
    # Создаем сессию БД если не передана
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    try:
        # Получаем все accounts
        accounts = db.query(Account).all()
        
        for account in accounts:
            stats['checked'] += 1
            
            # I6.2: Проверяем отозван ли сертификат
            # Получаем серийный номер по CN из маппинга
            serial = cn_to_serial.get(account.cn)
            
            if serial is None:
                # Не нашли сертификат для этого CN, пропускаем
                continue
            
            is_revoked = serial in revoked_serials
            
            if is_revoked and not account.is_revoked:
                # I6.2: Отмечаем как отозванный
                account.is_revoked = True
                account.revoked_at = revoked_serials.get(serial, datetime.utcnow())
                stats['revoked'] += 1
            elif not is_revoked and account.is_revoked:
                # I6.4: Идемпотентность - сбрасываем статус если больше не в CRL
                # (CRL мог обновиться и сертификат мог быть восстановлен)
                account.is_revoked = False
                account.revoked_at = None
                stats['unrevoked'] += 1
            elif is_revoked and account.is_revoked:
                # I6.4: Идемпотентность - обновляем дату если изменилась
                new_revoked_at = revoked_serials.get(serial)
                if new_revoked_at and account.revoked_at != new_revoked_at:
                    account.revoked_at = new_revoked_at
        
        # Сохраняем изменения
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Error during CRL check: {e}", file=sys.stderr)
        stats['errors'] += 1
    finally:
        if close_db:
            db.close()
    
    return stats


def main():
    """Точка входа для скрипта."""
    stats = check_crl()
    print(f"CRL check completed: {stats}")
    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
