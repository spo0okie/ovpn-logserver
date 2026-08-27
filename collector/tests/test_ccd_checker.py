"""
Тесты для скрипта ccd_checker.py.

Покрывают инварианты I6.3, I6.4, I6.5:
- I6.3: ccd_checker обновляет has_ccd, ccd_updated_at
- I6.4: Скрипт идемпотентен (повторный запуск не ломает данные)
- I6.5: Скрипт не создает новых accounts (только UPDATE)
"""

import ast
import os
import sys
import time
from datetime import datetime, timedelta
from core.time import utcfromtimestamp, utcnow

import pytest

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collector.ccd_checker import check_ccd, find_ccd_files
from core.models import Account


# =============================================================================
# Хелперы для создания тестовых данных
# =============================================================================

def create_ccd_file(cn: str, content: str, tmp_path, mtime: datetime = None) -> str:
    """
    Создает тестовый CCD файл.
    
    Args:
        cn: Common Name клиента (имя файла)
        content: Содержимое файла
        tmp_path: Временная директория
        mtime: Время модификации (опционально)
    
    Returns:
        str: Путь к созданному файлу
    """
    ccd_path = tmp_path / cn
    ccd_path.write_text(content)
    
    if mtime:
        # Устанавливаем время модификации
        timestamp = mtime.timestamp()
        os.utime(str(ccd_path), (timestamp, timestamp))
    
    return str(ccd_path)


# =============================================================================
# Тесты I6.3: Обновление статуса CCD
# =============================================================================

class TestI63CcdUpdatesStatus:
    """
    Тесты для инварианта I6.3: ccd_checker обновляет has_ccd, ccd_updated_at.
    """

    def test_ccd_marks_has_ccd(self, db, tmp_path, mocker):
        """
        Тест I6.3: Пометка наличия CCD файла.
        
        Проверяем что check_ccd корректно отмечает has_ccd=True
        и устанавливает ccd_updated_at для accounts с CCD файлами.
        """
        # Создаем CCD файл
        mtime = utcnow() - timedelta(days=1)
        create_ccd_file('client_with_ccd', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path, mtime)
        
        # Создаем account
        account = Account(cn='client_with_ccd', has_ccd=False)
        db.add(account)
        db.commit()
        
        # Мокаем CCD_DIR
        mocker.patch('collector.ccd_checker.CCD_DIR', str(tmp_path))
        
        # Запускаем проверку CCD
        stats = check_ccd(db)
        
        # Проверяем статистику
        assert stats['checked'] == 1
        assert stats['with_ccd'] == 1
        assert stats['without_ccd'] == 0
        
        # Проверяем что account обновлен
        db.refresh(account)
        assert account.has_ccd is True
        assert account.ccd_updated_at is not None

    def test_ccd_unmarks_missing_ccd(self, db, tmp_path, mocker):
        """
        Тест I6.3 + I6.4: Снятие отметки при отсутствии CCD.
        
        Проверяем что check_ccd сбрасывает has_ccd=False
        для accounts без CCD файлов.
        """
        # Создаем account с has_ccd=True (CCD файл был удален)
        old_mtime = utcnow() - timedelta(days=7)
        account = Account(
            cn='client_without_ccd',
            has_ccd=True,
            ccd_updated_at=old_mtime
        )
        db.add(account)
        db.commit()
        
        # Мокаем CCD_DIR (пустая директория)
        mocker.patch('collector.ccd_checker.CCD_DIR', str(tmp_path))
        
        # Запускаем проверку CCD
        stats = check_ccd(db)
        
        # Проверяем статистику
        assert stats['checked'] == 1
        assert stats['with_ccd'] == 0
        assert stats['without_ccd'] == 1
        
        # Проверяем что отметка снята
        db.refresh(account)
        assert account.has_ccd is False
        assert account.ccd_updated_at is None

    def test_ccd_multiple_accounts(self, db, tmp_path, mocker):
        """
        Тест I6.3: Проверка нескольких accounts.
        """
        # Создаем CCD файлы только для client1 и client2
        create_ccd_file('client1', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path)
        create_ccd_file('client2', 'ifconfig-push 10.8.0.11 255.255.255.0', tmp_path)
        # client3 без CCD файла
        
        # Создаем accounts
        account1 = Account(cn='client1', has_ccd=False)
        account2 = Account(cn='client2', has_ccd=False)
        account3 = Account(cn='client3', has_ccd=False)
        db.add(account1)
        db.add(account2)
        db.add(account3)
        db.commit()
        
        # Мокаем CCD_DIR
        mocker.patch('collector.ccd_checker.CCD_DIR', str(tmp_path))
        
        # Запускаем проверку CCD
        stats = check_ccd(db)
        
        # Проверяем статистику
        assert stats['checked'] == 3
        assert stats['with_ccd'] == 2
        assert stats['without_ccd'] == 1
        
        # Проверяем статусы
        db.refresh(account1)
        db.refresh(account2)
        db.refresh(account3)
        
        assert account1.has_ccd is True
        assert account2.has_ccd is True
        assert account3.has_ccd is False

    def test_ccd_updated_at_matches_mtime(self, db, tmp_path, mocker):
        """
        Тест I6.3: Проверка что ccd_updated_at соответствует mtime файла.
        """
        # Создаем CCD файл с конкретным временем модификации
        mtime = datetime(2024, 6, 15, 12, 0, 0)
        create_ccd_file('client', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path, mtime)
        
        # Создаем account
        account = Account(cn='client', has_ccd=False)
        db.add(account)
        db.commit()
        
        # Мокаем CCD_DIR
        mocker.patch('collector.ccd_checker.CCD_DIR', str(tmp_path))
        
        # Запускаем проверку CCD
        stats = check_ccd(db)
        
        # Проверяем что ccd_updated_at соответствует mtime
        db.refresh(account)
        assert account.has_ccd is True
        # Сравниваем с точностью до секунды (так как mtime имеет ограниченную точность)
        assert account.ccd_updated_at is not None
        # ccd_updated_at хранится в naive-UTC (utcfromtimestamp от epoch файла).
        expected = utcfromtimestamp(mtime.timestamp())
        assert abs((account.ccd_updated_at - expected).total_seconds()) < 2


# =============================================================================
# Тесты I6.4: Идемпотентность
# =============================================================================

class TestI64Idempotency:
    """
    Тесты для инварианта I6.4: Скрипт идемпотентен.
    """

    def test_ccd_check_idempotent(self, db, tmp_path, mocker):
        """
        Тест I6.4: Идемпотентность ccd_checker.
        
        Проверяем что повторный запуск не ломает данные.
        """
        # Создаем CCD файл
        mtime = utcnow() - timedelta(days=1)
        create_ccd_file('client', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path, mtime)
        
        # Создаем account
        account = Account(cn='client', has_ccd=False)
        db.add(account)
        db.commit()
        
        # Мокаем CCD_DIR
        mocker.patch('collector.ccd_checker.CCD_DIR', str(tmp_path))
        
        # Первый запуск
        stats1 = check_ccd(db)
        assert stats1['with_ccd'] == 1
        
        db.refresh(account)
        first_updated_at = account.ccd_updated_at
        
        # Второй запуск (идемпотентность)
        stats2 = check_ccd(db)
        
        # Проверяем что данные не сломались
        db.refresh(account)
        assert account.has_ccd is True
        assert account.ccd_updated_at == first_updated_at

    def test_ccd_check_handles_missing_dir(self, db, mocker):
        """
        Тест I6.4: Обработка отсутствующей директории.
        """
        # Мокаем несуществующую директорию
        mocker.patch('collector.ccd_checker.CCD_DIR', '/nonexistent/path')
        
        # Создаем account
        account = Account(cn='client', has_ccd=True, ccd_updated_at=utcnow())
        db.add(account)
        db.commit()
        
        # Запускаем проверку - не должно быть ошибок
        stats = check_ccd(db)
        
        assert stats['checked'] == 1
        assert stats['without_ccd'] == 1  # Все считаются без CCD
        
        # Проверяем что has_ccd сброшен
        db.refresh(account)
        assert account.has_ccd is False


# =============================================================================
# Тесты I6.5: Только UPDATE операции
# =============================================================================

class TestI65UpdateOnly:
    """
    Тесты для инварианта I6.5: Только UPDATE, никаких INSERT для accounts.
    """

    def test_no_new_accounts_created(self, db, tmp_path, mocker):
        """
        Тест I6.5: Проверяем что CCD checker не создает accounts.
        """
        # Создаем CCD файлы для несуществующих accounts
        create_ccd_file('unknown_client1', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path)
        create_ccd_file('unknown_client2', 'ifconfig-push 10.8.0.11 255.255.255.0', tmp_path)
        
        # Считаем количество accounts до
        count_before = db.query(Account).count()
        
        # Мокаем CCD_DIR
        mocker.patch('collector.ccd_checker.CCD_DIR', str(tmp_path))
        
        # Запускаем проверку
        stats = check_ccd(db)
        
        # Проверяем что количество accounts не изменилось
        count_after = db.query(Account).count()
        assert count_before == count_after
        
        # Проверяем что unknown_client не созданы
        assert db.query(Account).filter_by(cn='unknown_client1').first() is None
        assert db.query(Account).filter_by(cn='unknown_client2').first() is None

    def test_static_analysis_no_insert(self):
        """
        Тест I6.5: Статический анализ кода на отсутствие INSERT для accounts.
        """
        # Читаем исходный код
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'ccd_checker.py'
        )
        
        with open(script_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Парсим AST
        tree = ast.parse(source)
        
        # Ищем вызовы db.add()
        add_calls = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'add':
                        add_calls.append(node)
        
        # Проверяем что нет db.add() для Account
        for call in add_calls:
            if call.args and isinstance(call.args[0], ast.Name):
                if 'account' in call.args[0].id.lower():
                    pytest.fail(f"Found db.add() for account: {ast.dump(call)}")


# =============================================================================
# Тесты вспомогательных функций
# =============================================================================

class TestHelperFunctions:
    """
    Тесты для вспомогательных функций.
    """

    def test_find_ccd_files(self, tmp_path):
        """
        Тест find_ccd_files.
        """
        # Создаем несколько CCD файлов
        mtime1 = utcnow() - timedelta(days=1)
        mtime2 = utcnow() - timedelta(days=2)
        
        create_ccd_file('client1', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path, mtime1)
        create_ccd_file('client2', 'ifconfig-push 10.8.0.11 255.255.255.0', tmp_path, mtime2)
        
        # Создаем поддиректорию (должна быть проигнорирована)
        subdir = tmp_path / 'subdir'
        subdir.mkdir()
        
        files = find_ccd_files(str(tmp_path))

        assert len(files) == 2
        assert 'client1' in files
        assert 'client2' in files

        # mtime хранится в naive-UTC (utcfromtimestamp от epoch файла)
        expected1 = utcfromtimestamp(mtime1.timestamp())
        expected2 = utcfromtimestamp(mtime2.timestamp())
        assert abs((files['client1'] - expected1).total_seconds()) < 2
        assert abs((files['client2'] - expected2).total_seconds()) < 2

    def test_find_ccd_files_ignores_off_suffix(self, tmp_path):
        """
        Файл <cn>_OFF (usr.push при disable, архив для админов) — это
        отсутствие CCD, он игнорируется и не порождает CN 'client2_OFF'.
        """
        create_ccd_file('client1', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path)
        create_ccd_file('client2_OFF', 'ifconfig-push 10.8.0.11 255.255.255.0', tmp_path)

        files = find_ccd_files(str(tmp_path))

        assert set(files) == {'client1'}

    def test_find_ccd_files_cn_with_dot_not_truncated(self, tmp_path):
        """
        M4: CN с точкой (john.doe) не должен обрезаться до 'john'.
        CCD-файл именуется ровно по CN — используем полное имя файла.
        """
        create_ccd_file('john.doe', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path)

        files = find_ccd_files(str(tmp_path))

        assert 'john.doe' in files, "CN с точкой обрезан — has_ccd попадёт не тому аккаунту"
        assert 'john' not in files

    def test_find_ccd_files_skips_backup_files(self, tmp_path):
        """Скрытые и backup-файлы (.swp, name~) игнорируются."""
        create_ccd_file('client1', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path)
        create_ccd_file('client1~', 'backup', tmp_path)
        create_ccd_file('.hidden', 'x', tmp_path)

        files = find_ccd_files(str(tmp_path))

        assert 'client1' in files
        assert 'client1~' not in files
        assert '.hidden' not in files

    def test_find_ccd_files_empty_dir(self, tmp_path):
        """
        Тест find_ccd_files с пустой директорией.
        """
        files = find_ccd_files(str(tmp_path))

        assert files == {}

    def test_find_ccd_files_nonexistent_dir(self):
        """
        Тест find_ccd_files с несуществующей директорией.
        """
        files = find_ccd_files('/nonexistent/path')
        
        assert files == {}

    def test_find_ccd_files_ignores_subdirs(self, tmp_path):
        """
        Тест что find_ccd_files игнорирует поддиректории.
        """
        # Создаем CCD файл
        create_ccd_file('client', 'ifconfig-push 10.8.0.10 255.255.255.0', tmp_path)
        
        # Создаем поддиректорию с файлом
        subdir = tmp_path / 'subdir'
        subdir.mkdir()
        (subdir / 'file.txt').write_text('content')
        
        files = find_ccd_files(str(tmp_path))

        assert len(files) == 1
        assert 'client' in files
        assert 'subdir' not in files


# =============================================================================
# Тесты мультисайта: per-site статус в ccd_status + агрегат в accounts
# =============================================================================

class TestMultisiteCcdStatus:
    """
    CCD-файлы лежат на каждом сервере отдельно; checker ведёт строки
    ccd_status своего сервера (строка = CCD есть) и пересчитывает агрегат
    accounts.has_ccd («есть хотя бы на одном сервере»).
    """

    def _server(self, db, name):
        from collector.server_registry import resolve_server_id
        return resolve_server_id(db, name)

    def test_per_site_rows_created(self, db, tmp_path, mocker):
        """Строка ccd_status = CCD есть; <cn>_OFF строк не порождает."""
        from core.models import CcdStatus

        create_ccd_file('client1', 'a', tmp_path)
        create_ccd_file('client2_OFF', 'b', tmp_path)
        db.add(Account(cn='client1'))
        db.add(Account(cn='client2'))
        db.commit()

        sid = self._server(db, 'chl')
        stats = check_ccd(db, ccd_dir=str(tmp_path), server_id=sid)

        assert stats['site_found'] == 1
        rows = {r.cn for r in db.query(CcdStatus).filter_by(server_id=sid).all()}
        assert rows == {'client1'}

        # агрегат: у client1 CCD есть, у client2 только архивный _OFF
        assert db.query(Account).filter_by(cn='client1').one().has_ccd is True
        assert db.query(Account).filter_by(cn='client2').one().has_ccd is False

    def test_ccd_on_one_site_keeps_aggregate(self, db, tmp_path, mocker):
        """CCD есть только на одном из сайтов — агрегат True; исчез везде — False."""
        site_a = tmp_path / 'a'
        site_b = tmp_path / 'b'
        site_a.mkdir()
        site_b.mkdir()
        create_ccd_file('client', 'a', site_a)   # CCD только на site-a
        db.add(Account(cn='client'))
        db.commit()

        sid_a = self._server(db, 'site-a')
        sid_b = self._server(db, 'site-b')
        check_ccd(db, ccd_dir=str(site_a), server_id=sid_a)
        check_ccd(db, ccd_dir=str(site_b), server_id=sid_b)

        account = db.query(Account).filter_by(cn='client').one()
        assert account.has_ccd is True

        # выключение на site-a: usr.push переименовывает файл в _OFF
        (site_a / 'client').rename(site_a / 'client_OFF')
        check_ccd(db, ccd_dir=str(site_a), server_id=sid_a)

        db.refresh(account)
        assert account.has_ccd is False

    def test_checker_does_not_touch_other_site_rows(self, db, tmp_path, mocker):
        """Пустая директория одного сайта не удаляет строки другого."""
        from core.models import CcdStatus

        site_a = tmp_path / 'a'
        site_b = tmp_path / 'b'
        site_a.mkdir()
        site_b.mkdir()
        create_ccd_file('client', 'a', site_a)
        db.add(Account(cn='client'))
        db.commit()

        sid_a = self._server(db, 'site-a')
        sid_b = self._server(db, 'site-b')
        check_ccd(db, ccd_dir=str(site_a), server_id=sid_a)
        # site-b пустой: своих строк нет, чужие не трогает
        stats_b = check_ccd(db, ccd_dir=str(site_b), server_id=sid_b)

        assert stats_b['site_removed'] == 0
        assert db.query(CcdStatus).filter_by(server_id=sid_a).count() == 1
        assert db.query(Account).filter_by(cn='client').one().has_ccd is True

    def test_removed_file_deletes_row(self, db, tmp_path, mocker):
        """Файл исчез совсем — строка ccd_status удаляется, агрегат сбрасывается."""
        from core.models import CcdStatus

        path = create_ccd_file('client', 'a', tmp_path)
        db.add(Account(cn='client'))
        db.commit()

        sid = self._server(db, 'chl')
        check_ccd(db, ccd_dir=str(tmp_path), server_id=sid)
        assert db.query(CcdStatus).filter_by(server_id=sid).count() == 1

        os.remove(path)
        stats = check_ccd(db, ccd_dir=str(tmp_path), server_id=sid)

        assert stats['site_removed'] == 1
        assert db.query(CcdStatus).filter_by(server_id=sid).count() == 0
        assert db.query(Account).filter_by(cn='client').one().has_ccd is False
