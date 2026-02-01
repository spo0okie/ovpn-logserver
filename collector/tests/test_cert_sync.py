"""
Тесты для скрипта cert_sync.py.

Покрывают инварианты I6.1, I6.4, I6.5:
- I6.1: cert_sync обновляет valid_from, valid_to из сертификатов
- I6.4: Скрипт идемпотентен (повторный запуск не ломает данные)
- I6.5: Скрипт не создает новых accounts (только UPDATE)
"""

import ast
import os
import sys
from datetime import datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collector.cert_sync import sync_certificates, extract_cert_info, find_cert_files
from core.models import Account


# =============================================================================
# Хелперы для создания тестовых сертификатов
# =============================================================================

def create_test_certificate(cn: str, valid_from: datetime, valid_to: datetime, tmp_path) -> str:
    """
    Создает тестовый сертификат в формате PEM.
    
    Args:
        cn: Common Name для сертификата
        valid_from: Дата начала действия
        valid_to: Дата окончания действия
        tmp_path: Временная директория
    
    Returns:
        str: Путь к созданному файлу сертификата
    """
    # Генерируем приватный ключ
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Создаем самоподписанный сертификат
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "RU"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        valid_from
    ).not_valid_after(
        valid_to
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(cn)]),
        critical=False,
    ).sign(key, hashes.SHA256(), default_backend())
    
    # Сохраняем сертификат
    cert_path = tmp_path / f"{cn}.crt"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    
    return str(cert_path)


# =============================================================================
# Фикстуры
# =============================================================================

@pytest.fixture
def sample_cert_data():
    """
    Фикстура с тестовыми данными для сертификата.
    """
    now = datetime.utcnow()
    return {
        'cn': 'testclient',
        'valid_from': now,
        'valid_to': now + timedelta(days=365),
    }


# =============================================================================
# Тесты I6.1: Обновление сроков сертификата
# =============================================================================

class TestI61CertSyncUpdatesDates:
    """
    Тесты для инварианта I6.1: cert_sync обновляет valid_from, valid_to.
    """

    def test_cert_sync_updates_dates(self, db, tmp_path, mocker):
        """
        Тест I6.1: Обновление сроков сертификата.
        
        Проверяем что sync_certificates корректно обновляет valid_from и valid_to
        из сертификатов в БД.
        """
        # Создаем тестовый сертификат
        now = datetime.utcnow()
        valid_from = now
        valid_to = now + timedelta(days=365)
        
        cert_path = create_test_certificate('testclient', valid_from, valid_to, tmp_path)
        
        # Создаем account в БД
        account = Account(cn='testclient')
        db.add(account)
        db.commit()
        
        # Мокаем CERTS_DIR
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        
        # Запускаем синхронизацию
        stats = sync_certificates(db)
        
        # Проверяем статистику
        assert stats['processed'] == 1
        assert stats['updated'] == 1
        assert stats['errors'] == 0
        
        # Проверяем что даты обновлены
        db.refresh(account)
        assert account.valid_from is not None
        assert account.valid_to is not None
        # Проверяем что даты примерно соответствуют (с точностью до секунд)
        assert abs((account.valid_from - valid_from).total_seconds()) < 2
        assert abs((account.valid_to - valid_to).total_seconds()) < 2

    def test_cert_sync_multiple_certs(self, db, tmp_path, mocker):
        """
        Тест I6.1: Синхронизация нескольких сертификатов.
        """
        now = datetime.utcnow()
        
        # Создаем несколько сертификатов
        cert1_path = create_test_certificate('client1', now, now + timedelta(days=365), tmp_path)
        cert2_path = create_test_certificate('client2', now, now + timedelta(days=180), tmp_path)
        
        # Создаем accounts в БД
        account1 = Account(cn='client1')
        account2 = Account(cn='client2')
        db.add(account1)
        db.add(account2)
        db.commit()
        
        # Мокаем CERTS_DIR
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        
        # Запускаем синхронизацию
        stats = sync_certificates(db)
        
        # Проверяем статистику
        assert stats['processed'] == 2
        assert stats['updated'] == 2
        
        # Проверяем что оба account обновлены
        db.refresh(account1)
        db.refresh(account2)
        assert account1.valid_from is not None
        assert account2.valid_from is not None

    def test_cert_sync_skips_nonexistent_account(self, db, tmp_path, mocker):
        """
        Тест I6.5: Пропуск сертификатов без соответствующего account.
        
        Проверяем что sync_certificates не создает новые accounts.
        """
        now = datetime.utcnow()
        
        # Создаем сертификат
        cert_path = create_test_certificate('unknown_client', now, now + timedelta(days=365), tmp_path)
        
        # НЕ создаем account в БД
        
        # Мокаем CERTS_DIR
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        
        # Запускаем синхронизацию
        stats = sync_certificates(db)
        
        # Проверяем статистику - сертификат обработан но не обновлен
        assert stats['processed'] == 1
        assert stats['updated'] == 0  # Не обновлен так как нет account
        
        # Проверяем что account не создан
        account = db.query(Account).filter_by(cn='unknown_client').first()
        assert account is None


# =============================================================================
# Тесты I6.4: Идемпотентность
# =============================================================================

class TestI64Idempotency:
    """
    Тесты для инварианта I6.4: Скрипт идемпотентен.
    """

    def test_cert_sync_idempotent(self, db, tmp_path, mocker):
        """
        Тест I6.4: Идемпотентность cert_sync.
        
        Проверяем что повторный запуск не ломает данные.
        """
        now = datetime.utcnow()
        valid_from = now
        valid_to = now + timedelta(days=365)
        
        # Создаем сертификат
        cert_path = create_test_certificate('testclient', valid_from, valid_to, tmp_path)
        
        # Создаем account с уже установленными датами
        account = Account(
            cn='testclient',
            valid_from=datetime(2024, 1, 1),
            valid_to=datetime(2025, 1, 1)
        )
        db.add(account)
        db.commit()
        
        # Мокаем CERTS_DIR
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        
        # Первый запуск
        stats1 = sync_certificates(db)
        assert stats1['updated'] == 1
        
        db.refresh(account)
        first_valid_from = account.valid_from
        first_valid_to = account.valid_to
        
        # Второй запуск (идемпотентность)
        stats2 = sync_certificates(db)
        assert stats2['updated'] == 1  # Обновляется но данные те же
        
        # Проверяем что данные не сломались
        db.refresh(account)
        assert account.valid_from == first_valid_from
        assert account.valid_to == first_valid_to

    def test_cert_sync_handles_missing_certs_dir(self, db, mocker):
        """
        Тест I6.4: Обработка отсутствующей директории.
        """
        # Мокаем несуществующую директорию
        mocker.patch('collector.cert_sync.CERTS_DIR', '/nonexistent/path')
        
        # Запускаем синхронизацию - не должно быть ошибок
        stats = sync_certificates(db)
        
        assert stats['processed'] == 0
        assert stats['errors'] == 0  # Не считаем отсутствие директории ошибкой


# =============================================================================
# Тесты I6.5: Только UPDATE операции
# =============================================================================

class TestI65UpdateOnly:
    """
    Тесты для инварианта I6.5: Только UPDATE, никаких INSERT для accounts.
    """

    def test_no_insert_for_new_cn(self, db, tmp_path, mocker):
        """
        Тест I6.5: Проверяем что новые CN не создают accounts.
        """
        now = datetime.utcnow()
        
        # Создаем сертификат для несуществующего account
        cert_path = create_test_certificate('new_client', now, now + timedelta(days=365), tmp_path)
        
        # Считаем количество accounts до
        count_before = db.query(Account).count()
        
        # Мокаем CERTS_DIR
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        
        # Запускаем синхронизацию
        stats = sync_certificates(db)
        
        # Проверяем что количество accounts не изменилось
        count_after = db.query(Account).count()
        assert count_before == count_after

    def test_static_analysis_no_insert(self):
        """
        Тест I6.5: Статический анализ кода на отсутствие INSERT для accounts.
        """
        # Читаем исходный код
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cert_sync.py'
        )
        
        with open(script_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Парсим AST
        tree = ast.parse(source)
        
        # Ищем вызовы db.add() - это признак INSERT
        add_calls = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'add':
                        add_calls.append(node)
        
        # Проверяем что нет db.add() для Account
        # Может быть db.add() для других сущностей, но не для Account
        for call in add_calls:
            if isinstance(call.args[0], ast.Name):
                if 'account' in call.args[0].id.lower():
                    pytest.fail(f"Found db.add() for account: {ast.dump(call)}")


# =============================================================================
# Тесты вспомогательных функций
# =============================================================================

class TestHelperFunctions:
    """
    Тесты для вспомогательных функций.
    """

    def test_extract_cert_info(self, tmp_path):
        """
        Тест extract_cert_info.
        """
        now = datetime.utcnow()
        cert_path = create_test_certificate('test_cn', now, now + timedelta(days=365), tmp_path)
        
        info = extract_cert_info(cert_path)
        
        assert info is not None
        assert info['cn'] == 'test_cn'
        assert info['valid_from'] is not None
        assert info['valid_to'] is not None

    def test_extract_cert_info_invalid_file(self, tmp_path):
        """
        Тест extract_cert_info с невалидным файлом.
        """
        invalid_cert = tmp_path / 'invalid.crt'
        invalid_cert.write_text('not a valid certificate')
        
        info = extract_cert_info(str(invalid_cert))
        
        assert info is None

    def test_find_cert_files(self, tmp_path):
        """
        Тест find_cert_files.
        """
        now = datetime.utcnow()
        
        # Создаем несколько сертификатов
        create_test_certificate('client1', now, now + timedelta(days=365), tmp_path)
        create_test_certificate('client2', now, now + timedelta(days=365), tmp_path)
        
        # Создаем файл с другим расширением
        other_file = tmp_path / 'readme.txt'
        other_file.write_text('not a cert')
        
        cert_files = find_cert_files(str(tmp_path))
        
        assert len(cert_files) == 2
        assert all(f.endswith('.crt') for f in cert_files)

    def test_find_cert_files_empty_dir(self, tmp_path):
        """
        Тест find_cert_files с пустой директорией.
        """
        cert_files = find_cert_files(str(tmp_path))
        
        assert cert_files == []

    def test_find_cert_files_nonexistent_dir(self):
        """
        Тест find_cert_files с несуществующей директорией.
        """
        cert_files = find_cert_files('/nonexistent/path')
        
        assert cert_files == []
