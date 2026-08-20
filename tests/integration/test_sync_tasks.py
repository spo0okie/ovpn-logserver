"""
Тест синхронизаций и обновления метаданных.

Проверяет инвариант I10.3: синхронизации обновляют метаданные.
"""

import pytest
from datetime import datetime, timedelta
from tests.integration.conftest import create_test_cert


class TestSyncTasks:
    """
    Тесты синхронизаций.
    
    Проверяют:
    - Синхронизация сертификатов обновляет valid_from/valid_to
    - Синхронизация CCD обновляет has_ccd флаг
    - Синхронизация CRL обновляет is_revoked флаг
    - Операции идемпотентны
    """
    
    def test_cert_sync_updates_valid_dates(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: синхронизация сертификатов обновляет даты валидности.
        
        Проверяет что после запуска cert_sync:
        - valid_from устанавливается из сертификата
        - valid_to устанавливается из сертификата
        """
        # Arrange
        from core.models import Account
        
        test_cn = "test_cert_sync"

        # Создаем тестовый сертификат
        cert_path = create_test_cert(tmp_certs_dir, test_cn, valid_days=180)

        # Act
        stats = run_cert_sync(tmp_certs_dir)

        # Assert: в multi-cert модели запись создаётся на пару (cn, serial)
        assert stats['processed'] >= 1
        assert stats['created'] >= 1

        account = db.query(Account).filter_by(cn=test_cn).first()
        assert account is not None
        assert account.valid_from is not None, "valid_from должен быть установлен"
        assert account.valid_to is not None, "valid_to должен быть установлен"
        
        # Проверяем что даты соответствуют сертификату
        expected_valid_to = datetime.utcnow() + timedelta(days=180)
        # Допуск в 1 день из-за округления
        assert (account.valid_to - expected_valid_to).days <= 1
    
    def test_cert_sync_idempotent(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: синхронизация сертификатов идемпотентна.
        
        Проверяет что повторный запуск cert_sync:
        - Не ломает данные
        - Обновляет записи корректно
        """
        # Arrange
        from core.models import Account
        
        test_cn = "idempotent_test"
        create_test_cert(tmp_certs_dir, test_cn, valid_days=90)

        # Act - первый запуск: запись создаётся
        stats1 = run_cert_sync(tmp_certs_dir)
        account = db.query(Account).filter_by(cn=test_cn).first()
        assert account is not None
        valid_to_1 = account.valid_to

        # Act - второй запуск: та же пара (cn, serial) → обновление, не дубль
        stats2 = run_cert_sync(tmp_certs_dir)
        db.refresh(account)
        valid_to_2 = account.valid_to

        # Assert
        assert valid_to_1 == valid_to_2, "Даты должны совпадать после повторного запуска"
        assert stats1['created'] == 1
        assert stats2['created'] == 0, "Повторный запуск не должен создавать дубли"
        assert stats2['updated'] == 1
        assert db.query(Account).filter_by(cn=test_cn).count() == 1


    def test_cert_sync_creates_accounts_for_certificates(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: cert_sync создаёт accounts по найденным сертификатам.

        В multi-cert модели запись заводится на пару (cn, serial_number) —
        cert_sync является источником accounts для неотозванных сертификатов.
        """
        # Arrange
        from core.models import Account

        create_test_cert(tmp_certs_dir, "cert_user_a")
        create_test_cert(tmp_certs_dir, "cert_user_b")

        # Act
        stats = run_cert_sync(tmp_certs_dir)

        # Assert
        assert stats['processed'] == 2
        assert stats['created'] == 2
        assert db.query(Account).filter_by(cn="cert_user_a").count() == 1
        assert db.query(Account).filter_by(cn="cert_user_b").count() == 1
    
    def test_cert_sync_multiple_certs(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: синхронизация множества сертификатов.
        
        Проверяет что cert_sync корректно обрабатывает несколько сертификатов.
        """
        # Arrange
        from core.models import Account
        
        users = ["multi_user_1", "multi_user_2", "multi_user_3"]
        for cn in users:
            create_test_cert(tmp_certs_dir, cn, valid_days=60 + users.index(cn) * 30)

        # Act
        stats = run_cert_sync(tmp_certs_dir)

        # Assert
        assert stats['processed'] == 3
        assert stats['created'] == 3

        for cn in users:
            account = db.query(Account).filter_by(cn=cn).first()
            assert account is not None
            assert account.valid_from is not None
            assert account.valid_to is not None
    
    def test_cert_sync_handles_invalid_certs(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: обработка невалидных сертификатов.
        
        Проверяет что cert_sync корректно обрабатывает поврежденные файлы.
        """
        # Arrange
        from core.models import Account
        
        # Создаем валидный аккаунт и сертификат
        valid_cn = "valid_cert_user"
        create_test_cert(tmp_certs_dir, valid_cn)
        
        # Создаем невалидный файл сертификата
        invalid_cert = tmp_certs_dir / "invalid.crt"
        invalid_cert.write_text("This is not a valid certificate")
        
        db.commit()
        
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        assert stats['processed'] == 2  # Оба файла обработаны
        assert stats['created'] == 1    # Только валидный записан
        assert stats['errors'] == 1     # Один файл с ошибкой
    
    def test_cert_sync_skips_non_cert_files(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: пропуск не-сертификатных файлов.
        
        Проверяет что cert_sync игнорирует файлы без расширения .crt
        """
        # Arrange
        from core.models import Account
        
        test_cn = "cert_only_user"
        create_test_cert(tmp_certs_dir, test_cn)
        
        # Создаем файлы с другими расширениями
        (tmp_certs_dir / "readme.txt").write_text("Not a cert")
        (tmp_certs_dir / "config.yaml").write_text("key: value")
        (tmp_certs_dir / "backup.key").write_text("private key data")
        
        db.commit()
        
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        assert stats['processed'] == 1  # Только .crt файл
        assert stats['created'] == 1
    
    def test_cert_sync_updates_account_metadata(self, db, tmp_certs_dir, run_cert_sync, api_client, auth_headers):
        """
        Тест: обновленные метаданные доступны через API.
        
        Проверяет что после синхронизации данные видны в API.
        """
        # Arrange
        from core.models import Account
        
        test_cn = "api_sync_user"
        create_test_cert(tmp_certs_dir, test_cn, valid_days=365)

        # Act
        run_cert_sync(tmp_certs_dir)

        # Assert - проверяем через API (multi-cert: даты внутри certificates[])
        response = api_client.get(f"/api/v1/accounts/{test_cn}", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["cn"] == test_cn
        assert data["cert_count"] >= 1
        cert = data["certificates"][0]
        assert cert["valid_from"] is not None
        assert cert["valid_to"] is not None
    
    def test_cert_sync_empty_directory(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: синхронизация пустой директории.
        
        Проверяет что cert_sync корректно работает с пустой директорией.
        """
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        assert stats['processed'] == 0
        assert stats['updated'] == 0
        assert stats['errors'] == 0
    
    def test_cert_sync_cert_renewal(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: обновление сертификата (renewal).
        
        Проверяет что при обновлении сертификата с новыми датами:
        - Даты в БД обновляются
        - Старые данные заменяются
        """
        # Arrange
        from core.models import Account
        
        test_cn = "renewal_user"
        old_valid_to = datetime.utcnow() + timedelta(days=30)

        # Первый сертификат (короткий срок) — запись создаётся синхронизацией
        create_test_cert(tmp_certs_dir, test_cn, valid_days=30)
        run_cert_sync(tmp_certs_dir)
        account = db.query(Account).filter_by(cn=test_cn).first()
        assert account is not None
        first_valid_to = account.valid_to

        # Перевыпуск: тот же CN, тот же файл — но новый сертификат с большим сроком
        for f in tmp_certs_dir.glob("*.crt"):
            f.unlink()
        create_test_cert(tmp_certs_dir, test_cn, valid_days=365)

        # Act
        run_cert_sync(tmp_certs_dir)

        # Assert: продлённый сертификат отражён в БД
        renewed = (
            db.query(Account)
            .filter_by(cn=test_cn)
            .order_by(Account.valid_to.desc())
            .first()
        )
        assert renewed.valid_to > first_valid_to
        assert renewed.valid_to > old_valid_to
