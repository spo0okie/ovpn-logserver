"""
Тесты для скрипта crl_checker.py.

Покрывают инварианты I6.2, I6.4, I6.5:
- I6.2: crl_checker обновляет is_revoked, revoked_at из CRL
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

from collector.crl_checker import check_crl, parse_crl
from core.models import Account


# =============================================================================
# Хелперы для создания тестовых данных
# =============================================================================

def create_test_certificate(cn: str, valid_from: datetime, valid_to: datetime, tmp_path) -> tuple:
    """
    Создает тестовый сертификат и возвращает путь и серийный номер.
    
    Returns:
        tuple: (путь к файлу, серийный номер)
    """
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
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
    ).sign(key, hashes.SHA256(), default_backend())
    
    cert_path = tmp_path / f"{cn}.crt"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    
    return str(cert_path), cert.serial_number


def create_test_crl(revoked_serials: dict, tmp_path, issuer_cn: str = "Test CA") -> str:
    """
    Создает тестовый CRL файл.
    
    Args:
        revoked_serials: dict {serial_number: revocation_date}
        tmp_path: Временная директория
        issuer_cn: CN для issuer
    
    Returns:
        str: Путь к созданному CRL файлу
    """
    # Генерируем ключ для CA
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Создаем issuer
    issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn),
    ])
    
    # Создаем список отозванных сертификатов
    revoked_certs = []
    for serial, revoked_at in revoked_serials.items():
        revoked_cert = x509.RevokedCertificateBuilder().serial_number(
            int(serial) if isinstance(serial, str) else serial
        ).revocation_date(
            revoked_at
        ).build(default_backend())
        revoked_certs.append(revoked_cert)
    
    # Создаем CRL
    builder = x509.CertificateRevocationListBuilder()
    builder = builder.issuer_name(issuer)
    builder = builder.last_update(datetime.utcnow())
    builder = builder.next_update(datetime.utcnow() + timedelta(days=7))
    
    for revoked_cert in revoked_certs:
        builder = builder.add_revoked_certificate(revoked_cert)
    
    crl = builder.sign(
        private_key=ca_key,
        algorithm=hashes.SHA256(),
        backend=default_backend()
    )
    
    # Сохраняем CRL
    crl_path = tmp_path / "crl.pem"
    crl_path.write_bytes(crl.public_bytes(serialization.Encoding.PEM))
    
    return str(crl_path)


# =============================================================================
# Тесты I6.2: Обновление статуса отзыва
# =============================================================================

class TestI62CrlUpdatesRevocation:
    """
    Тесты для инварианта I6.2: crl_checker обновляет is_revoked, revoked_at.
    """

    def test_crl_marks_revoked(self, db, tmp_path, mocker):
        """
        Тест I6.2: Пометка отозванных сертификатов.

        Проверяем что check_crl корректно отмечает is_revoked=True
        для сертификатов в CRL. Теперь используется serial_number из account.
        """
        now = datetime.utcnow()

        # Создаем сертификат
        cert_path, serial = create_test_certificate('revoked_client', now, now + timedelta(days=365), tmp_path)

        # Создаем CRL с этим сертификатом
        revoked_at = now - timedelta(days=1)
        crl_path = create_test_crl({serial: revoked_at}, tmp_path)

        # Создаем account с правильным serial_number (как строка)
        account = Account(cn='revoked_client', serial_number=str(serial), is_revoked=False)
        db.add(account)
        db.commit()

        # Мокаем CRL_FILE и CERTS_DIR
        mocker.patch('collector.crl_checker.CRL_FILE', crl_path)
        mocker.patch('collector.crl_checker.CERTS_DIR', str(tmp_path))

        # Запускаем проверку CRL
        stats = check_crl(db)

        # Проверяем статистику
        assert stats['checked'] == 1
        assert stats['revoked'] == 1

        # Проверяем что account помечен как отозванный
        db.refresh(account)
        assert account.is_revoked is True
        assert account.revoked_at is not None

    def test_crl_unmarks_non_revoked(self, db, tmp_path, mocker):
        """
        Тест I6.2 + I6.4: Снятие отметки отзыва.
        
        Проверяем что check_crl сбрасывает is_revoked=False
        для сертификатов не в CRL (идемпотентность).
        """
        now = datetime.utcnow()
        
        # Создаем сертификат (нужен для маппинга CN -> serial)
        cert_path, serial = create_test_certificate('restored_client', now, now + timedelta(days=365), tmp_path)
        
        # Создаем пустой CRL (без отозванных)
        crl_path = create_test_crl({}, tmp_path)
        
        # Создаем account помеченный как отозванный
        account = Account(
            cn='restored_client',
            is_revoked=True,
            revoked_at=now - timedelta(days=7)
        )
        db.add(account)
        db.commit()
        
        # Мокаем CRL_FILE и CERTS_DIR
        mocker.patch('collector.crl_checker.CRL_FILE', crl_path)
        mocker.patch('collector.crl_checker.CERTS_DIR', str(tmp_path))
        
        # Запускаем проверку CRL
        stats = check_crl(db)
        
        # Проверяем статистику
        assert stats['checked'] == 1
        assert stats['unrevoked'] == 1
        
        # Проверяем что отметка снята
        db.refresh(account)
        assert account.is_revoked is False
        assert account.revoked_at is None

    def test_crl_multiple_accounts(self, db, tmp_path, mocker):
        """
        Тест I6.2: Проверка нескольких accounts.
        Теперь используется serial_number из account напрямую.
        """
        now = datetime.utcnow()

        # Создаем сертификаты
        cert1_path, serial1 = create_test_certificate('client1', now, now + timedelta(days=365), tmp_path)
        cert2_path, serial2 = create_test_certificate('client2', now, now + timedelta(days=365), tmp_path)
        cert3_path, serial3 = create_test_certificate('client3', now, now + timedelta(days=365), tmp_path)

        # Создаем CRL только с client1 и client2
        crl_path = create_test_crl({
            serial1: now - timedelta(days=1),
            serial2: now - timedelta(days=2),
        }, tmp_path)

        # Создаем accounts с правильными serial_number
        account1 = Account(cn='client1', serial_number=str(serial1), is_revoked=False)
        account2 = Account(cn='client2', serial_number=str(serial2), is_revoked=False)
        account3 = Account(cn='client3', serial_number=str(serial3), is_revoked=False)
        db.add(account1)
        db.add(account2)
        db.add(account3)
        db.commit()

        # Мокаем CRL_FILE и CERTS_DIR
        mocker.patch('collector.crl_checker.CRL_FILE', crl_path)
        mocker.patch('collector.crl_checker.CERTS_DIR', str(tmp_path))

        # Запускаем проверку CRL
        stats = check_crl(db)

        # Проверяем статистику
        assert stats['checked'] == 3
        assert stats['revoked'] == 2

        # Проверяем статусы
        db.refresh(account1)
        db.refresh(account2)
        db.refresh(account3)

        assert account1.is_revoked is True
        assert account2.is_revoked is True
        assert account3.is_revoked is False  # Не в CRL


# =============================================================================
# Тесты I6.4: Идемпотентность
# =============================================================================

class TestI64Idempotency:
    """
    Тесты для инварианта I6.4: Скрипт идемпотентен.
    """

    def test_crl_check_idempotent(self, db, tmp_path, mocker):
        """
        Тест I6.4: Идемпотентность crl_checker.

        Проверяем что повторный запуск не ломает данные.
        Теперь используется serial_number из account напрямую.
        """
        now = datetime.utcnow()

        # Создаем сертификат
        cert_path, serial = create_test_certificate('client', now, now + timedelta(days=365), tmp_path)

        # Создаем CRL
        revoked_at = now - timedelta(days=1)
        crl_path = create_test_crl({serial: revoked_at}, tmp_path)

        # Создаем account с правильным serial_number
        account = Account(cn='client', serial_number=str(serial), is_revoked=False)
        db.add(account)
        db.commit()

        # Мокаем CRL_FILE и CERTS_DIR
        mocker.patch('collector.crl_checker.CRL_FILE', crl_path)
        mocker.patch('collector.crl_checker.CERTS_DIR', str(tmp_path))

        # Первый запуск
        stats1 = check_crl(db)
        assert stats1['revoked'] == 1

        db.refresh(account)
        first_revoked_at = account.revoked_at

        # Второй запуск (идемпотентность)
        stats2 = check_crl(db)

        # Проверяем что данные не сломались
        db.refresh(account)
        assert account.is_revoked is True
        assert account.revoked_at == first_revoked_at

    def test_crl_check_missing_file(self, db, mocker):
        """
        Тест I6.4: Обработка отсутствующего CRL файла.
        """
        # Мокаем несуществующий файл
        mocker.patch('collector.crl_checker.CRL_FILE', '/nonexistent/crl.pem')
        
        # Запускаем проверку
        stats = check_crl(db)
        
        # Должна быть ошибка
        assert stats['errors'] == 1


# =============================================================================
# Тесты I6.5: Только UPDATE операции
# =============================================================================

class TestI65UpdateOnly:
    """
    Тесты для инварианта I6.5: Только UPDATE, никаких INSERT для accounts.
    """

    def test_no_new_accounts_created(self, db, tmp_path, mocker):
        """
        Тест I6.5: Проверяем что CRL checker не создает accounts.
        """
        now = datetime.utcnow()
        
        # Создаем CRL с серийными номерами
        crl_path = create_test_crl({12345: now}, tmp_path)
        
        # Считаем количество accounts до
        count_before = db.query(Account).count()
        
        # Мокаем CRL_FILE
        mocker.patch('collector.crl_checker.CRL_FILE', crl_path)
        
        # Запускаем проверку
        stats = check_crl(db)
        
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
            'crl_checker.py'
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

    def test_parse_crl(self, tmp_path):
        """
        Тест parse_crl.
        """
        now = datetime.utcnow()
        
        # Создаем CRL
        revoked_serials = {12345: now - timedelta(days=1)}
        crl_path = create_test_crl(revoked_serials, tmp_path)
        
        info = parse_crl(crl_path)
        
        assert info is not None
        assert 'revoked_certs' in info
        assert 'last_update' in info
        assert 'next_update' in info

    def test_parse_crl_invalid_file(self, tmp_path):
        """
        Тест parse_crl с невалидным файлом.
        """
        invalid_crl = tmp_path / 'invalid.crl'
        invalid_crl.write_text('not a valid crl')
        
        info = parse_crl(str(invalid_crl))
        
        assert info is None

    def test_parse_crl_empty(self, tmp_path):
        """
        Тест parse_crl с пустым CRL.
        """
        crl_path = create_test_crl({}, tmp_path)
        
        info = parse_crl(crl_path)
        
        assert info is not None
        assert info['revoked_certs'] == {}
