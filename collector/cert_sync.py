"""
Скрипт синхронизации сертификатов.

Обновляет valid_from и valid_to в БД на основе данных из сертификатов.

Инварианты:
- I6.1: Обновляет valid_from, valid_to из сертификатов
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

from core.database import SessionLocal
from core.models import Account
from collector.config import CERTS_DIR, CERT_EXTENSION


def extract_cert_info(cert_path: str) -> dict:
    """
    Извлекает информацию из сертификата.
    
    Args:
        cert_path: Путь к файлу сертификата в формате PEM
    
    Returns:
        dict: Словарь с полями:
            - cn: Common Name из сертификата
            - valid_from: datetime начала действия
            - valid_to: datetime окончания действия
            - None если не удалось распарсить
    """
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()
        
        # Парсим сертификат
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        
        # Извлекаем CN из Subject
        cn = None
        for attr in cert.subject:
            if attr.oid == x509.NameOID.COMMON_NAME:
                cn = attr.value
                break
        
        if not cn:
            return None
        
        # Получаем даты валидности
        valid_from = cert.not_valid_before
        valid_to = cert.not_valid_after
        
        return {
            'cn': cn,
            'valid_from': valid_from,
            'valid_to': valid_to,
        }
    except Exception as e:
        print(f"Error parsing certificate {cert_path}: {e}", file=sys.stderr)
        return None


def find_cert_files(certs_dir: str) -> list:
    """
    Находит все файлы сертификатов в директории.
    
    Args:
        certs_dir: Путь к директории с сертификатами
    
    Returns:
        list: Список путей к файлам сертификатов
    """
    certs_path = Path(certs_dir)
    if not certs_path.exists() or not certs_path.is_dir():
        return []
    
    # Ищем файлы с расширением .crt (или другим указанным)
    cert_files = list(certs_path.glob(f"*{CERT_EXTENSION}"))
    return [str(f) for f in cert_files]


def sync_certificates(db=None, certs_dir: str = None) -> dict:
    """
    Синхронизирует даты сертификатов с БД.
    
    Сканирует директорию с сертификатами и обновляет сроки в БД.
    Только UPDATE операции - не создает новые accounts.
    
    Args:
        db: Сессия базы данных (если None, создается новая)
        certs_dir: Директория с сертификатами (если None, используется CERTS_DIR)
    
    Returns:
        dict: Статистика синхронизации:
            - processed: количество обработанных сертификатов
            - updated: количество обновленных записей
            - errors: количество ошибок
    
    Invariants: I6.1, I6.4, I6.5
    """
    stats = {
        'processed': 0,
        'updated': 0,
        'errors': 0,
    }
    
    # Используем переданную директорию или дефолтную
    target_certs_dir = certs_dir or CERTS_DIR
    
    # Находим все сертификаты
    cert_files = find_cert_files(target_certs_dir)
    
    # Создаем сессию БД если не передана
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    try:
        for cert_path in cert_files:
            stats['processed'] += 1
            
            # Извлекаем информацию из сертификата
            cert_info = extract_cert_info(cert_path)
            if cert_info is None:
                stats['errors'] += 1
                continue
            
            # I6.5: Только UPDATE, не создаем новые accounts
            # Ищем существующий account по CN
            account = db.query(Account).filter_by(cn=cert_info['cn']).first()
            
            if account is None:
                # I6.5: Не создаем новый account, пропускаем
                continue
            
            # I6.1: Обновляем даты сертификата
            # I6.4: Идемпотентность - просто обновляем значения
            account.valid_from = cert_info['valid_from']
            account.valid_to = cert_info['valid_to']
            
            stats['updated'] += 1
        
        # Сохраняем изменения
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Error during certificate sync: {e}", file=sys.stderr)
        stats['errors'] += 1
    finally:
        if close_db:
            db.close()
    
    return stats


def main():
    """Точка входа для скрипта."""
    stats = sync_certificates()
    print(f"Certificate sync completed: {stats}")
    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
