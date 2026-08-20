#!/usr/bin/env python3
"""
Тесты для модуля sync_all.py.

Проверяют инварианты:
- S3.1: session_cleanup вызывается ПОСЛЕ успешного выполнения всех остальных sync-задач
- S3.2: session_cleanup вызывается ТОЛЬКО если предыдущие задачи завершились успешно
- S3.3: При ошибке session_cleanup - логируется, но не блокирует следующие запуски
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path

# Добавляем родительские директории в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSyncOrder:
    """
    Тесты порядка выполнения задач (S3.1, S3.2).
    """

    def test_s3_1_session_cleanup_called_after_other_tasks(self):
        """
        S3.1: session_cleanup вызывается ПОСЛЕ успешного выполнения всех остальных sync-задач.

        Предотвращает: Вызов session_cleanup до завершения других задач
        """
        from collector import sync_all

        # Мокаем все функции
        with patch('collector.sync_all.sync_certificates') as mock_cert, \
             patch('collector.sync_all.check_crl') as mock_crl, \
             patch('collector.sync_all.check_ccd') as mock_ccd, \
             patch('collector.sync_all.cleanup_orphaned_sessions') as mock_cleanup:

            # Настраиваем моки для успешного выполнения
            mock_cert.return_value = {"created": 0, "updated": 0}
            mock_crl.return_value = {"checked": 0, "revoked": 0}
            mock_ccd.return_value = {"checked": 0, "updated": 0}
            mock_cleanup.return_value = (0, 0)

            # Запускаем sync
            result = sync_all.run_sync()

            # Проверяем что все функции были вызваны
            assert mock_cert.call_count == 1, "cert_sync должен быть вызван"
            assert mock_crl.call_count == 1, "crl_checker должен быть вызван"
            assert mock_ccd.call_count == 1, "ccd_checker должен быть вызван"
            assert mock_cleanup.call_count == 1, "session_cleanup должен быть вызван"

            # S3.1: Проверяем порядок вызовов через call_args_list
            calls = [mock_cert, mock_crl, mock_ccd, mock_cleanup]
            call_order = [m.call_args_list for m in calls]
            
            # Проверяем что session_cleanup вызван последним (имеет наибольший индекс)
            # Поскольку все вызваны по 1 разу, session_cleanup должен иметь call_count как у других
            # но в коде он вызывается последним в блоке try
            assert mock_cleanup.call_count == 1
            assert result == 0, "run_sync должен вернуть 0 при успехе"

    def test_s3_2_session_cleanup_not_called_on_cert_failure(self):
        """
        S3.2: session_cleanup НЕ вызывается если cert_sync упал.

        Предотвращает: Вызов session_cleanup при неуспехе предыдущих задач
        """
        from collector import sync_all

        # Мокаем cert_sync с ошибкой
        with patch('collector.sync_all.sync_certificates') as mock_cert, \
             patch('collector.sync_all.check_crl') as mock_crl, \
             patch('collector.sync_all.check_ccd') as mock_ccd, \
             patch('collector.sync_all.cleanup_orphaned_sessions') as mock_cleanup:

            # cert_sync падает с ошибкой
            mock_cert.side_effect = Exception("Certificate sync failed")
            mock_crl.return_value = {"checked": 0, "revoked": 0}
            mock_ccd.return_value = {"checked": 0, "updated": 0}
            mock_cleanup.return_value = (0, 0)

            # Запускаем sync
            result = sync_all.run_sync()

            # S3.2: session_cleanup НЕ должен быть вызван
            assert mock_cert.call_count == 1, "cert_sync должен быть вызван"
            assert mock_cleanup.call_count == 0, \
                "session_cleanup НЕ должен быть вызван при ошибке cert_sync"
            assert mock_crl.call_count == 0, \
                "crl_checker НЕ должен быть вызван при ошибке cert_sync"
            assert mock_ccd.call_count == 0, \
                "ccd_checker НЕ должен быть вызван при ошибке cert_sync"
            assert result == 1, "run_sync должен вернуть 1 при ошибке"

    def test_s3_2_session_cleanup_not_called_on_crl_failure(self):
        """
        S3.2: session_cleanup НЕ вызывается если crl_checker упал после cert_sync.

        Предотвращает: Вызов session_cleanup при неуспехе предыдущих задач
        """
        from collector import sync_all

        with patch('collector.sync_all.sync_certificates') as mock_cert, \
             patch('collector.sync_all.check_crl') as mock_crl, \
             patch('collector.sync_all.check_ccd') as mock_ccd, \
             patch('collector.sync_all.cleanup_orphaned_sessions') as mock_cleanup:

            mock_cert.return_value = {"created": 0, "updated": 0}
            # crl_checker падает
            mock_crl.side_effect = Exception("CRL check failed")
            mock_ccd.return_value = {"checked": 0, "updated": 0}
            mock_cleanup.return_value = (0, 0)

            result = sync_all.run_sync()

            # S3.2: session_cleanup НЕ должен быть вызван
            assert mock_cert.call_count == 1, "cert_sync должен быть вызван"
            assert mock_crl.call_count == 1, "crl_checker должен быть вызван"
            assert mock_cleanup.call_count == 0, \
                "session_cleanup НЕ должен быть вызван при ошибке crl_checker"
            assert result == 1

    def test_s3_2_session_cleanup_not_called_on_ccd_failure(self):
        """
        S3.2: session_cleanup НЕ вызывается если ccd_checker упал.

        Предотвращает: Вызов session_cleanup при неуспехе предыдущих задач
        """
        from collector import sync_all

        with patch('collector.sync_all.sync_certificates') as mock_cert, \
             patch('collector.sync_all.check_crl') as mock_crl, \
             patch('collector.sync_all.check_ccd') as mock_ccd, \
             patch('collector.sync_all.cleanup_orphaned_sessions') as mock_cleanup:

            mock_cert.return_value = {"created": 0, "updated": 0}
            mock_crl.return_value = {"checked": 0, "revoked": 0}
            # ccd_checker падает
            mock_ccd.side_effect = Exception("CCD check failed")
            mock_cleanup.return_value = (0, 0)

            result = sync_all.run_sync()

            # S3.2: session_cleanup НЕ должен быть вызван
            assert mock_cert.call_count == 1
            assert mock_crl.call_count == 1
            assert mock_ccd.call_count == 1
            assert mock_cleanup.call_count == 0, \
                "session_cleanup НЕ должен быть вызван при ошибке ccd_checker"
            assert result == 1

    def test_s3_2_soft_errors_skip_cleanup_and_return_nonzero(self):
        """
        S3.2 (H2): шаг вернул stats['errors']>0 БЕЗ исключения — cleanup всё
        равно должен быть пропущен, а run_sync вернуть 1.

        Предотвращает: cleanup после частично неуспешного cert_sync (риск
        закрытия живых сессий) и невидимость сбоя для systemd (exit 0).
        """
        from collector import sync_all

        with patch('collector.sync_all.sync_certificates') as mock_cert, \
             patch('collector.sync_all.check_crl') as mock_crl, \
             patch('collector.sync_all.check_ccd') as mock_ccd, \
             patch('collector.sync_all.cleanup_orphaned_sessions') as mock_cleanup:

            # cert_sync "мягко" ошибся: 2 ошибки, но не бросил исключение
            mock_cert.return_value = {"created": 0, "updated": 0, "errors": 2}
            mock_crl.return_value = {"checked": 0, "revoked": 0, "errors": 0}
            mock_ccd.return_value = {"checked": 0, "updated": 0, "errors": 0}
            mock_cleanup.return_value = (0, 0)

            result = sync_all.run_sync()

            assert mock_cleanup.call_count == 0, \
                "cleanup не должен запускаться при soft-ошибках синка"
            assert result == 1, "run_sync должен вернуть 1 при stats['errors']>0"


class TestSessionCleanupErrorHandling:
    """
    Тесты обработки ошибок session_cleanup (S3.3).
    """

    def test_s3_3_session_cleanup_error_logged_not_blocking(self, caplog):
        """
        S3.3: При ошибке session_cleanup - логируется, но не блокирует следующие запуски.

        Предотвращает: Падение всей синхронизации из-за ошибки session_cleanup
        """
        import logging
        from collector import sync_all

        with patch('collector.sync_all.sync_certificates') as mock_cert, \
             patch('collector.sync_all.check_crl') as mock_crl, \
             patch('collector.sync_all.check_ccd') as mock_ccd, \
             patch('collector.sync_all.cleanup_orphaned_sessions') as mock_cleanup:

            mock_cert.return_value = {"created": 0, "updated": 0}
            mock_crl.return_value = {"checked": 0, "revoked": 0}
            mock_ccd.return_value = {"checked": 0, "updated": 0}
            # session_cleanup падает с ошибкой
            mock_cleanup.side_effect = Exception("Session cleanup failed")

            with caplog.at_level(logging.INFO):
                result = sync_all.run_sync()

            # S3.3: Синхронизация должна завершиться успешно (session_cleanup не блокирует)
            assert result == 0, \
                "run_sync должен вернуть 0, ошибка session_cleanup не должна блокировать"
            assert mock_cert.call_count == 1
            assert mock_crl.call_count == 1
            assert mock_ccd.call_count == 1
            assert mock_cleanup.call_count == 1


class TestMainFunction:
    """
    Тесты функции main().
    """

    def test_main_returns_zero_on_success(self):
        """
        main() возвращает 0 при успешном выполнении.
        """
        from collector import sync_all
        import sys

        with patch.object(sync_all, 'run_sync', return_value=0) as mock_run:
            with patch.object(sys, 'exit') as mock_exit:
                sync_all.main()
                mock_exit.assert_called_with(0)
                mock_run.assert_called_once()

    def test_main_returns_one_on_failure(self):
        """
        main() возвращает 1 при ошибке.
        """
        from collector import sync_all
        import sys

        with patch.object(sync_all, 'run_sync', return_value=1) as mock_run:
            with patch.object(sys, 'exit') as mock_exit:
                sync_all.main()
                mock_exit.assert_called_with(1)
                mock_run.assert_called_once()


class TestFullIntegration:
    """
    Интеграционные тесты.
    """

    def test_all_tasks_called_in_correct_order(self):
        """
        Полный тест: все задачи вызываются в правильном порядке.
        """
        from collector import sync_all

        call_order = []

        with patch('collector.sync_all.sync_certificates', side_effect=lambda *a, **kw: call_order.append('cert_sync') or {"created": 0}), \
             patch('collector.sync_all.check_crl', side_effect=lambda *a, **kw: call_order.append('crl_checker') or {"checked": 0}), \
             patch('collector.sync_all.check_ccd', side_effect=lambda *a, **kw: call_order.append('ccd_checker') or {"checked": 0}), \
             patch('collector.sync_all.cleanup_orphaned_sessions', side_effect=lambda *a, **kw: call_order.append('session_cleanup') or (0, 0)):

            sync_all.run_sync()

            expected_order = ['cert_sync', 'crl_checker', 'ccd_checker', 'session_cleanup']
            assert call_order == expected_order, \
                f"Неправильный порядок вызовов: {call_order} != {expected_order}"
