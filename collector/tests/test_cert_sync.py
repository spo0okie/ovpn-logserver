"""
Тесты для скрипта cert_sync.py.

Покрывают инварианты I6.1, I6.4, I6.5:
- I6.1: cert_sync обновляет valid_from, valid_to из сертификатов
- I6.4: Скрипт идемпотентен (повторный запуск не ломает данные)
- I6.5: Скрипт создает accounts для неотозванных сертификатов (INSERT или UPDATE)
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

from sqlalchemy.exc import IntegrityError

from collector.cert_sync import sync_certificates, extract_cert_info, find_cert_files, parse_crl
from core.models import Account


# =============================================================================
# Хелперы для создания тестовых сертификатов
# =============================================================================

def create_test_certificate(cn: str, valid_from: datetime, valid_to: datetime, tmp_path,
                            serial_number: int = None) -> str:
    """
    Создает тестовый сертификат в формате PEM.

    Args:
        cn: Common Name для сертификата
        valid_from: Дата начала действия
        valid_to: Дата окончания действия
        tmp_path: Временная директория
        serial_number: Опциональный серийный номер (для тестов CRL)

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

    # Используем переданный серийный номер или генерируем случайный
    cert_serial = serial_number if serial_number else x509.random_serial_number()

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        cert_serial
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


def create_test_crl(tmp_path, revoked_serials: list = None) -> str:
    """
    Создает тестовый CRL файл.

    Args:
        tmp_path: Временная директория
        revoked_serials: Список серийных номеров для отзыва

    Returns:
        str: Путь к созданному CRL файлу
    """
    # Генерируем приватный ключ для CRL
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Создаем issuer
    issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Test CA"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "RU"),
    ])

    # Создаем список отозванных сертификатов
    revoked_certs = []
    if revoked_serials:
        for serial in revoked_serials:
            revoked_cert = x509.RevokedCertificateBuilder().serial_number(
                serial
            ).revocation_date(
                datetime.utcnow()
            ).build(default_backend())
            revoked_certs.append(revoked_cert)

    # Создаем CRL
    crl_builder = x509.CertificateRevocationListBuilder()
    crl_builder = crl_builder.issuer_name(issuer)
    crl_builder = crl_builder.last_update(datetime.utcnow())
    crl_builder = crl_builder.next_update(datetime.utcnow() + timedelta(days=30))

    for revoked_cert in revoked_certs:
        crl_builder = crl_builder.add_revoked_certificate(revoked_cert)

    crl = crl_builder.sign(key, hashes.SHA256(), default_backend())

    # Сохраняем CRL
    crl_path = tmp_path / "crl.pem"
    crl_path.write_bytes(crl.public_bytes(serialization.Encoding.PEM))

    return str(crl_path)


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
        из сертификатов в БД. Теперь account идентифицируется по паре (cn, serial_number).
        """
        # Создаем тестовый сертификат
        now = datetime.utcnow()
        valid_from = now
        valid_to = now + timedelta(days=365)

        cert_path = create_test_certificate('testclient', valid_from, valid_to, tmp_path)

        # Получаем серийный номер из созданного сертификата
        from collector.cert_sync import extract_cert_info
        cert_info = extract_cert_info(cert_path)
        serial_number = cert_info['serial_number']

        # Создаем account в БД с правильным serial_number
        account = Account(cn='testclient', serial_number=serial_number)
        db.add(account)
        db.commit()

        # Мокаем CERTS_DIR и CRL_FILE
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        mocker.patch('collector.cert_sync.CRL_FILE', str(tmp_path / "nonexistent.crl"))

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
        Теперь account идентифицируется по паре (cn, serial_number).
        """
        now = datetime.utcnow()

        # Создаем несколько сертификатов
        cert1_path = create_test_certificate('client1', now, now + timedelta(days=365), tmp_path)
        cert2_path = create_test_certificate('client2', now, now + timedelta(days=180), tmp_path)

        # Получаем серийные номера из созданных сертификатов
        from collector.cert_sync import extract_cert_info
        cert1_info = extract_cert_info(cert1_path)
        cert2_info = extract_cert_info(cert2_path)

        # Создаем accounts в БД с правильными serial_number
        account1 = Account(cn='client1', serial_number=cert1_info['serial_number'])
        account2 = Account(cn='client2', serial_number=cert2_info['serial_number'])
        db.add(account1)
        db.add(account2)
        db.commit()

        # Мокаем CERTS_DIR и CRL_FILE
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        mocker.patch('collector.cert_sync.CRL_FILE', str(tmp_path / "nonexistent.crl"))

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
        Теперь account идентифицируется по паре (cn, serial_number).
        """
        now = datetime.utcnow()
        valid_from = now
        valid_to = now + timedelta(days=365)

        # Создаем сертификат
        cert_path = create_test_certificate('testclient', valid_from, valid_to, tmp_path)

        # Получаем серийный номер из созданного сертификата
        from collector.cert_sync import extract_cert_info
        cert_info = extract_cert_info(cert_path)
        serial_number = cert_info['serial_number']

        # Создаем account с уже установленными датами и правильным serial_number
        account = Account(
            cn='testclient',
            serial_number=serial_number,
            valid_from=datetime(2024, 1, 1),
            valid_to=datetime(2025, 1, 1)
        )
        db.add(account)
        db.commit()

        # Мокаем CERTS_DIR и CRL_FILE
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        mocker.patch('collector.cert_sync.CRL_FILE', str(tmp_path / "nonexistent.crl"))

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
        mocker.patch('collector.cert_sync.CRL_FILE', '/nonexistent/crl.pem')

        # Запускаем синхронизацию - не должно быть ошибок
        stats = sync_certificates(db)

        assert stats['processed'] == 0
        assert stats['errors'] == 0  # Не считаем отсутствие директории ошибкой


# =============================================================================
# Тесты I6.5: Создание accounts для неотозванных сертификатов
# =============================================================================

class TestI65CreateAccounts:
    """
    Тесты для инварианта I6.5: Создание accounts для неотозванных сертификатов.
    """

    def test_create_account_for_new_cn(self, db, tmp_path, mocker):
        """
        Тест I6.5: Создание account для нового CN.

        Проверяем что sync_certificates создает новые accounts для
        неотозванных сертификатов.
        """
        now = datetime.utcnow()

        # Создаем сертификат для несуществующего account
        cert_path = create_test_certificate('new_client', now, now + timedelta(days=365), tmp_path)

        # Считаем количество accounts до
        count_before = db.query(Account).count()

        # Мокаем CERTS_DIR и CRL_FILE
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        mocker.patch('collector.cert_sync.CRL_FILE', str(tmp_path / "nonexistent.crl"))

        # Запускаем синхронизацию
        stats = sync_certificates(db)

        # Проверяем статистику
        assert stats['processed'] == 1
        assert stats['created'] == 1
        assert stats['updated'] == 0

        # Проверяем что account создан
        count_after = db.query(Account).count()
        assert count_after == count_before + 1

        # Проверяем что account имеет правильные данные
        account = db.query(Account).filter_by(cn='new_client').first()
        assert account is not None
        assert account.valid_from is not None
        assert account.valid_to is not None

    def test_skip_revoked_certificate(self, db, tmp_path, mocker):
        """
        Тест I6.5: Пропуск отозванных сертификатов.

        Проверяем что sync_certificates не создает accounts для
        отозванных сертификатов.
        """
        now = datetime.utcnow()

        # Создаем сертификаты с конкретными серийными номерами
        serial1 = 12345
        serial2 = 67890

        cert1_path = create_test_certificate('client1', now, now + timedelta(days=365), tmp_path, serial1)
        cert2_path = create_test_certificate('client2', now, now + timedelta(days=365), tmp_path, serial2)

        # Создаем CRL с отзывом первого сертификата
        crl_path = create_test_crl(tmp_path, revoked_serials=[serial1])

        # Считаем количество accounts до
        count_before = db.query(Account).count()

        # Мокаем CERTS_DIR и CRL_FILE
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        mocker.patch('collector.cert_sync.CRL_FILE', crl_path)

        # Запускаем синхронизацию
        stats = sync_certificates(db)

        # Проверяем статистику
        assert stats['processed'] == 2
        assert stats['created'] == 1  # Только один account создан
        assert stats['skipped_revoked'] == 1  # Один пропущен (отозван)

        # Проверяем что создан только account для неотозванного сертификата
        account1 = db.query(Account).filter_by(cn='client1').first()
        account2 = db.query(Account).filter_by(cn='client2').first()

        assert account1 is None  # Отозван - не создан
        assert account2 is not None  # Не отозван - создан

    def test_mixed_certs_existing_and_new(self, db, tmp_path, mocker):
        """
        Тест I6.5: Смешанные сертификаты (существующие и новые).

        Проверяем корректную обработку когда часть CN уже есть в БД,
        а часть — новые. Теперь account идентифицируется по паре (cn, serial_number).
        """
        now = datetime.utcnow()

        # Создаем сертификаты
        cert1_path = create_test_certificate('existing_client', now, now + timedelta(days=365), tmp_path)
        cert2_path = create_test_certificate('new_client', now, now + timedelta(days=365), tmp_path)

        # Получаем серийный номер из существующего сертификата
        from collector.cert_sync import extract_cert_info
        cert1_info = extract_cert_info(cert1_path)

        # Создаем один account заранее с правильным serial_number
        existing_account = Account(cn='existing_client', serial_number=cert1_info['serial_number'])
        db.add(existing_account)
        db.commit()

        # Мокаем CERTS_DIR и CRL_FILE
        mocker.patch('collector.cert_sync.CERTS_DIR', str(tmp_path))
        mocker.patch('collector.cert_sync.CERT_EXTENSION', '.crt')
        mocker.patch('collector.cert_sync.CRL_FILE', str(tmp_path / "nonexistent.crl"))

        # Запускаем синхронизацию
        stats = sync_certificates(db)

        # Проверяем статистику
        assert stats['processed'] == 2
        assert stats['created'] == 1  # Новый client
        assert stats['updated'] == 1  # Существующий client

        # Проверяем что оба account существуют
        assert db.query(Account).filter_by(cn='existing_client').first() is not None
        assert db.query(Account).filter_by(cn='new_client').first() is not None


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
        assert info['serial_number'] is not None

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

    def test_parse_crl_valid(self, tmp_path):
        """
        Тест parse_crl с валидным CRL файлом.
        Серийные номера в результате — нормализованные (hex uppercase).
        """
        from core.serial import normalize_serial

        serial1 = 11111
        serial2 = 22222
        crl_path = create_test_crl(tmp_path, revoked_serials=[serial1, serial2])

        revoked = parse_crl(crl_path)

        assert len(revoked) == 2
        assert normalize_serial(serial1) in revoked
        assert normalize_serial(serial2) in revoked

    def test_parse_crl_empty(self, tmp_path):
        """
        Тест parse_crl с пустым CRL (без отозванных).
        """
        crl_path = create_test_crl(tmp_path, revoked_serials=[])

        revoked = parse_crl(crl_path)

        assert len(revoked) == 0

    def test_parse_crl_nonexistent(self):
        """
        Тест parse_crl с несуществующим файлом.
        """
        revoked = parse_crl('/nonexistent/crl.pem')

        assert len(revoked) == 0


# =============================================================================
# M2: изоляция ошибок при синхронизации (покоммитная обработка)
# =============================================================================

class TestM2BatchIsolation:
    """Один конфликтный/гоночный сертификат не должен откатывать весь батч."""

    def test_upsert_creates_then_updates_idempotent(self, db):
        from collector.cert_sync import _upsert_account
        now = datetime.utcnow()
        info = {'cn': 'u1', 'serial_number': '123', 'valid_from': now,
                'valid_to': now + timedelta(days=365)}
        stats = {'created': 0, 'updated': 0, 'errors': 0}

        _upsert_account(db, info, stats)
        assert stats['created'] == 1
        acct = db.query(Account).filter_by(cn='u1', serial_number='123').first()
        assert acct is not None

        # повторный вызов с новыми датами → update, не дубль
        info2 = {**info, 'valid_to': now + timedelta(days=730)}
        _upsert_account(db, info2, stats)
        assert stats['updated'] == 1
        assert db.query(Account).filter_by(cn='u1', serial_number='123').count() == 1

    def test_recover_after_race_updates_existing(self, db):
        """Симуляция гонки: запись уже вставлена параллельно — _recover обновляет."""
        from collector.cert_sync import _recover_after_race
        now = datetime.utcnow()
        # эмулируем, что client_connect уже вставил account
        db.add(Account(cn='r1', serial_number='999', valid_from=now,
                       valid_to=now + timedelta(days=1)))
        db.commit()

        info = {'cn': 'r1', 'serial_number': '999', 'valid_from': now,
                'valid_to': now + timedelta(days=365)}
        stats = {'created': 0, 'updated': 0, 'errors': 0}
        _recover_after_race(db, info, stats)

        assert stats['updated'] == 1
        assert stats['errors'] == 0
        acct = db.query(Account).filter_by(cn='r1', serial_number='999').first()
        assert abs((acct.valid_to - info['valid_to']).total_seconds()) < 2

    def test_integrity_error_on_one_cert_does_not_lose_others(self, db, tmp_path, mocker):
        """
        Мок: первый commit падает IntegrityError (гонка), последующие проходят.
        Проверяем, что синхронизация не потеряла остальные сертификаты и не
        откатила весь батч (M2).
        """
        from collector import cert_sync
        now = datetime.utcnow()
        create_test_certificate('cA', now, now + timedelta(days=365), tmp_path)
        create_test_certificate('cB', now, now + timedelta(days=365), tmp_path)
        create_test_certificate('cC', now, now + timedelta(days=365), tmp_path)

        # Пустой CRL
        crl = tmp_path / 'crl.pem'
        mocker.patch('collector.cert_sync.parse_crl', return_value=set())

        real_commit = db.commit
        calls = {'n': 0}

        def flaky_commit():
            calls['n'] += 1
            if calls['n'] == 1:
                raise IntegrityError("stmt", {}, Exception("duplicate"))
            return real_commit()

        mocker.patch.object(db, 'commit', side_effect=flaky_commit)

        stats = cert_sync.sync_certificates(db=db, certs_dir=str(tmp_path),
                                            crl_path=str(crl))

        # Даже при сбое на одном сертификате остальные должны быть записаны.
        # Всего 3 сертификата: как минимум 2 успешно созданы.
        total_accounts = db.query(Account).count()
        assert total_accounts >= 2, f"батч потерял сертификаты: только {total_accounts}"


class TestMisconfiguredCertsDir:
    """
    Молчаливая опечатка в certs_dir/cert_extension превращала cert_sync в no-op:
    даты сертификатов не заполнялись, и понять это можно было только по пустым
    valid_to в БД. Проверяем, что такая ситуация логируется явно.
    """

    def test_warns_when_extension_does_not_match_files(self, tmp_path, caplog):
        import logging
        from collector.cert_sync import find_cert_files

        # В каталоге только .pem, а ищем .crt (реальный кейс с CA newcerts)
        (tmp_path / "0100.pem").write_text("x")
        (tmp_path / "0101.pem").write_text("x")

        with caplog.at_level(logging.ERROR):
            files = find_cert_files(str(tmp_path))

        assert files == []
        assert any("cert_extension" in r.message or ".pem" in r.getMessage()
                   for r in caplog.records), \
            "Несовпадение расширения должно логироваться с указанием найденных"

    def test_empty_dir_is_not_reported_as_misconfiguration(self, tmp_path, caplog):
        import logging
        from collector.cert_sync import find_cert_files

        with caplog.at_level(logging.ERROR):
            files = find_cert_files(str(tmp_path))

        assert files == []
        # Пустой каталог — не ошибка конфигурации, ERROR быть не должно
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
