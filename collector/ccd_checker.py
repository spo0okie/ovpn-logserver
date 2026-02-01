"""
Скрипт проверки CCD (Client Config Directory) файлов.

Обновляет has_ccd и ccd_updated_at в БД на основе наличия CCD файлов.

Инварианты:
- I6.3: Обновляет has_ccd, ccd_updated_at
- I6.4: Идемпотентен (повторный запуск не ломает данные)
- I6.5: Только UPDATE операции, никаких INSERT для accounts
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import Account
from collector.config import CCD_DIR


def find_ccd_files(ccd_dir: str) -> dict:
    """
    Находит все CCD файлы в директории.
    
    Args:
        ccd_dir: Путь к директории с CCD файлами
    
    Returns:
        dict: Словарь {filename: modification_time} для всех CCD файлов
    """
    ccd_path = Path(ccd_dir)
    if not ccd_path.exists() or not ccd_path.is_dir():
        return {}
    
    ccd_files = {}
    
    # Ищем все файлы в директории CCD
    for file_path in ccd_path.iterdir():
        if file_path.is_file():
            # Имя файла без расширения считаем CN клиента
            cn = file_path.stem
            # Получаем время модификации файла
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            ccd_files[cn] = mtime
    
    return ccd_files


def check_ccd(db=None, ccd_dir: str = None) -> dict:
    """
    Проверяет наличие CCD файлов и обновляет статус в БД.
    
    Находит все файлы в CCD_DIR, обновляет has_ccd=True, ccd_updated_at=NOW()
    для найденных. Обновляет has_ccd=False для не найденных.
    
    Args:
        db: Сессия базы данных (если None, создается новая)
        ccd_dir: Директория с CCD файлами (если None, используется CCD_DIR)
    
    Returns:
        dict: Статистика проверки:
            - checked: количество проверенных записей
            - with_ccd: количество записей с CCD
            - without_ccd: количество записей без CCD
            - errors: количество ошибок
    
    Invariants: I6.3, I6.4, I6.5
    """
    stats = {
        'checked': 0,
        'with_ccd': 0,
        'without_ccd': 0,
        'errors': 0,
    }
    
    # Используем переданную директорию или дефолтную
    target_ccd_dir = ccd_dir or CCD_DIR
    
    # Находим все CCD файлы
    ccd_files = find_ccd_files(target_ccd_dir)
    
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
            
            # I6.3: Проверяем наличие CCD файла
            if account.cn in ccd_files:
                # I6.3: CCD файл найден
                # I6.4: Идемпотентность - обновляем только если изменилось
                file_mtime = ccd_files[account.cn]
                
                if not account.has_ccd or account.ccd_updated_at != file_mtime:
                    account.has_ccd = True
                    account.ccd_updated_at = file_mtime
                
                stats['with_ccd'] += 1
            else:
                # I6.3: CCD файл не найден
                # I6.4: Идемпотентность - сбрасываем статус
                if account.has_ccd:
                    account.has_ccd = False
                    account.ccd_updated_at = None
                
                stats['without_ccd'] += 1
        
        # Сохраняем изменения
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Error during CCD check: {e}", file=sys.stderr)
        stats['errors'] += 1
    finally:
        if close_db:
            db.close()
    
    return stats


def main():
    """Точка входа для скрипта."""
    stats = check_ccd()
    print(f"CCD check completed: {stats}")
    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
