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
        account = Account(
            cn=test_cn,
            valid_from=None,
            valid_to=None,
            is_revoked=False,
            has_ccd=False
        )
        db.add(account)
        db.commit()
        
        # Создаем тестовый сертификат
        cert_path = create_test_cert(tmp_certs_dir, test_cn, valid_days=180)
        
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        assert stats['processed'] >= 1
        assert stats['updated'] >= 1
        
        db.refresh(account)
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
        account = Account(cn=test_cn)
        db.add(account)
        db.commit()
        
        create_test_cert(tmp_certs_dir, test_cn, valid_days=90)
        
        # Act - первый запуск
        stats1 = run_cert_sync(tmp_certs_dir)
        db.refresh(account)
        valid_to_1 = account.valid_to
        
        # Act - второй запуск
        stats2 = run_cert_sync(tmp_certs_dir)
        db.refresh(account)
        valid_to_2 = account.valid_to
        
        # Assert
        assert valid_to_1 == valid_to_2, "Даты должны совпадать после повторного запуска"
        assert stats1['updated'] == stats2['updated'], "Количество обновлений должно совпадать"
    
    def test_cert_sync_only_updates_existing_accounts(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: cert_sync только обновляет существующие аккаунты.
        
        Проверяет что:
        - Не создаются новые аккаунты для несуществующих сертификатов
        - Обновляются только существующие
        """
        # Arrange
        from core.models import Account
        
        # Создаем только один аккаунт
        existing_cn = "existing_user"
        Account(cn=existing_cn)
        db.add(Account(cn=existing_cn))
        db.commit()
        
        # Создаем сертификаты для существующего и несуществующего
        create_test_cert(tmp_certs_dir, existing_cn)
        create_test_cert(tmp_certs_dir, "non_existing_user")
        
        initial_count = db.query(Account).count()
        
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        final_count = db.query(Account).count()
        assert final_count == initial_count, "Не должно быть создано новых аккаунтов"
        assert stats['updated'] == 1, "Должен быть обновлен только 1 аккаунт"
    
    def test_cert_sync_multiple_certs(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: синхронизация множества сертификатов.
        
        Проверяет что cert_sync корректно обрабатывает несколько сертификатов.
        """
        # Arrange
        from core.models import Account
        
        users = ["multi_user_1", "multi_user_2", "multi_user_3"]
        for cn in users:
            db.add(Account(cn=cn))
            create_test_cert(tmp_certs_dir, cn, valid_days=60 + users.index(cn) * 30)
        
        db.commit()
        
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        assert stats['processed'] == 3
        assert stats['updated'] == 3
        
        for cn in users:
            account = db.query(Account).filter_by(cn=cn).first()
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
        db.add(Account(cn=valid_cn))
        create_test_cert(tmp_certs_dir, valid_cn)
        
        # Создаем невалидный файл сертификата
        invalid_cert = tmp_certs_dir / "invalid.crt"
        invalid_cert.write_text("This is not a valid certificate")
        
        db.commit()
        
        # Act
        stats = run_cert_sync(tmp_certs_dir)
        
        # Assert
        assert stats['processed'] == 2  # Оба файла обработаны
        assert stats['updated'] == 1    # Только валидный обновлен
        assert stats['errors'] == 1     # Один файл с ошибкой
    
    def test_cert_sync_skips_non_cert_files(self, db, tmp_certs_dir, run_cert_sync):
        """
        Тест: пропуск не-сертификатных файлов.
        
        Проверяет что cert_sync игнорирует файлы без расширения .crt
        """
        # Arrange
        from core.models import Account
        
        test_cn = "cert_only_user"
        db.add(Account(cn=test_cn))
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
        assert stats['updated'] == 1
    
    def test_cert_sync_updates_account_metadata(self, db, tmp_certs_dir, run_cert_sync, api_client, auth_headers):
        """
        Тест: обновленные метаданные доступны через API.
        
        Проверяет что после синхронизации данные видны в API.
        """
        # Arrange
        from core.models import Account
        
        test_cn = "api_sync_user"
        db.add(Account(cn=test_cn))
        create_test_cert(tmp_certs_dir, test_cn, valid_days=365)
        db.commit()
        
        # Act
        run_cert_sync(tmp_certs_dir)
        
        # Assert - проверяем через API
        response = api_client.get(f"/api/v1/accounts/{test_cn}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["cn"] == test_cn
        assert data["valid_from"] is not None
        assert data["valid_to"] is not None
    
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
        account = Account(
            cn=test_cn,
            valid_from=datetime.utcnow() - timedelta(days=335),
            valid_to=old_valid_to
        )
        db.add(account)
        db.commit()
        
        # Создаем новый сертификат с продленным сроком
        create_test_cert(tmp_certs_dir, test_cn, valid_days=365)
        
        # Act
        run_cert_sync(tmp_certs_dir)
        
        # Assert
        db.refresh(account)
        # Новая дата должна быть позже старой
        assert account.valid_to > old_valid_to
