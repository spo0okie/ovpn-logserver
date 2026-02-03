#!/usr/bin/env python3
"""
Tests for client_connect.py module.

Checks orphaned session invariants:
- C5.1: When connecting with active session - old one is marked as orphaned
- C5.2: Before creating session checks for active ones
- C5.3: orphaned session is closed (disconnected_at=NOW())
- C5.4: New session is created only after old one is closed
"""

import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGetActiveSessionsForAccount:
    """
    Tests for get_active_sessions_for_account function (C5.2).
    """

    def test_c5_2_finds_active_sessions(self, db):
        """
        C5.2: Function finds all active sessions for account.
        """
        from collector.client_connect import get_active_sessions_for_account
        from core.models import Account, Session

        # Create account
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        # Create active and closed sessions
        active_session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=1),
            source_ip="10.0.0.1",
            status='active'
        )
        closed_session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=2),
            disconnected_at=datetime.utcnow() - timedelta(hours=1),
            source_ip="10.0.0.1",
            status='closed'
        )

        db.add_all([active_session, closed_session])
        db.commit()

        # Find active sessions
        active_sessions = get_active_sessions_for_account(db, account.id)

        # Check that only active is found
        assert len(active_sessions) == 1
        assert active_sessions[0].id == active_session.id
        assert active_sessions[0].status == 'active'

    def test_c5_2_returns_empty_when_no_active(self, db):
        """
        C5.2: Returns empty list when no active sessions.
        """
        from collector.client_connect import get_active_sessions_for_account
        from core.models import Account

        # Create account without sessions
        account = Account(cn="new_user", serial_number="serial2")
        db.add(account)
        db.commit()

        active_sessions = get_active_sessions_for_account(db, account.id)

        assert active_sessions == []


class TestCloseOrphanedSession:
    """
    Tests for close_orphaned_session function (C5.1, C5.3).
    """

    def test_c5_1_sets_status_to_error(self, db):
        """
        C5.1: Function sets status 'error' for orphaned session.
        """
        from collector.client_connect import close_orphaned_session
        from core.models import Account, Session

        # Create account and session
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Close orphaned session
        close_orphaned_session(db, session)

        # Check status
        db.refresh(session)
        assert session.status == 'error'

    def test_c5_3_sets_disconnected_at(self, db):
        """
        C5.3: Function sets disconnected_at for orphaned session.
        """
        from collector.client_connect import close_orphaned_session
        from core.models import Account, Session

        # Create account and session
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        before_close = datetime.utcnow()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Close orphaned session
        close_orphaned_session(db, session)

        # Check disconnected_at
        db.refresh(session)
        assert session.disconnected_at is not None
        assert session.disconnected_at >= before_close

    def test_c5_1_logs_orphaned_session(self, db, caplog):
        """
        C5.1: Function logs orphaned session info.
        """
        import logging
        from collector.client_connect import close_orphaned_session
        from core.models import Account, Session

        # Create account and session
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow(),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(session)
        db.commit()

        # Close with logging
        with caplog.at_level(logging.INFO):
            close_orphaned_session(db, session)

        # Check log
        assert "Orphaned session closed" in caplog.text
        assert str(session.id) in caplog.text


class TestCloseOrphanedSessions:
    """
    Tests for close_orphaned_sessions function (C5.4).
    """

    def test_c5_4_closes_all_active_sessions(self, db):
        """
        C5.4: Function closes all active sessions for account.
        """
        from collector.client_connect import close_orphaned_sessions
        from core.models import Account, Session

        # Create account
        account = Account(cn="test_user", serial_number="serial1")
        db.add(account)
        db.commit()

        # Create multiple active sessions
        session1 = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=2),
            source_ip="10.0.0.1",
            status='active'
        )
        session2 = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=1),
            source_ip="10.0.0.1",
            status='active'
        )

        db.add_all([session1, session2])
        db.commit()

        # Close all orphaned sessions
        closed_count = close_orphaned_sessions(db, account.id)

        # Check that all are closed
        assert closed_count == 2

        # Check statuses
        db.refresh(session1)
        db.refresh(session2)

        assert session1.status == 'error'
        assert session2.status == 'error'
        assert session1.disconnected_at is not None
        assert session2.disconnected_at is not None

    def test_c5_4_returns_zero_when_no_active(self, db):
        """
        C5.4: Returns 0 when no active sessions.
        """
        from collector.client_connect import close_orphaned_sessions
        from core.models import Account

        # Create account without sessions
        account = Account(cn="new_user", serial_number="serial2")
        db.add(account)
        db.commit()

        closed_count = close_orphaned_sessions(db, account.id)

        assert closed_count == 0


class TestClientConnectOrphanedHandling:
    """
    Integration tests for client_connect with orphaned sessions.
    """

    def test_c5_1_c5_4_orphaned_closed_before_new_session(self, db):
        """
        C5.1, C5.4: When connecting with active session - old one is closed before new is created.
        """
        from collector.client_connect import client_connect
        from core.models import Account, Session

        # Create account
        account = Account(cn="reconnect_user", serial_number="serial1")
        db.add(account)
        db.commit()

        # Create existing active session
        old_session = Session(
            account_id=account.id,
            connected_at=datetime.utcnow() - timedelta(hours=1),
            source_ip="10.0.0.1",
            status='active'
        )
        db.add(old_session)
        db.commit()

        # Mock get_env_vars
        env_vars = {
            'common_name': 'reconnect_user',
            'serial_number': 'serial1',
            'trusted_ip': '10.0.0.2',
            'trusted_port': '12345',
            'ifconfig_pool_remote_ip': '10.8.0.5'
        }

        with patch('collector.client_connect.get_env_vars', return_value=env_vars), \
             patch('collector.client_connect.resolve_geoip', return_value=None):

            # Call client_connect
            result = client_connect(db_session=db)

            assert result == 0

            # Check that old session is closed
            db.refresh(old_session)
            assert old_session.status == 'error'
            assert old_session.disconnected_at is not None

            # Check that new session is created
            new_sessions = db.query(Session).filter(
                Session.account_id == account.id,
                Session.status == 'active'
            ).all()

            assert len(new_sessions) == 1
            assert new_sessions[0].source_ip == "10.0.0.2"

    def test_c5_2_no_active_sessions_new_connection(self, db):
        """
        C5.2: For new connection (no active sessions) only one session is created.
        """
        from collector.client_connect import client_connect
        from core.models import Account, Session

        # Create account WITHOUT existing sessions
        account = Account(cn="new_user", serial_number="serial1")
        db.add(account)
        db.commit()

        env_vars = {
            'common_name': 'new_user',
            'serial_number': 'serial1',
            'trusted_ip': '10.0.0.3',
            'trusted_port': '54321',
            'ifconfig_pool_remote_ip': '10.8.0.10'
        }

        with patch('collector.client_connect.get_env_vars', return_value=env_vars), \
             patch('collector.client_connect.resolve_geoip', return_value={'country': 'RU', 'city': 'Moscow'}):

            result = client_connect(db_session=db)

            assert result == 0

            # Check that one active session is created
            sessions = db.query(Session).filter(
                Session.account_id == account.id
            ).all()

            assert len(sessions) == 1
            assert sessions[0].status == 'active'
            assert sessions[0].source_ip == "10.0.0.3"

    def test_multiple_reconnects_all_closed(self, db):
        """
        On multiple reconnects all old sessions are closed.
        """
        from collector.client_connect import client_connect
        from core.models import Account, Session

        # Create account
        account = Account(cn="multi_user", serial_number="serial1")
        db.add(account)
        db.commit()

        # Create several "old" sessions
        for i in range(3):
            session = Session(
                account_id=account.id,
                connected_at=datetime.utcnow() - timedelta(hours=i+1),
                source_ip=f"10.0.0.{i+10}",
                status='active'
            )
            db.add(session)
        db.commit()

        env_vars = {
            'common_name': 'multi_user',
            'serial_number': 'serial1',
            'trusted_ip': '10.0.0.100',
            'trusted_port': '11111'
        }

        with patch('collector.client_connect.get_env_vars', return_value=env_vars), \
             patch('collector.client_connect.resolve_geoip', return_value=None):

            result = client_connect(db_session=db)

            assert result == 0

            # Check that all old sessions are closed
            closed_sessions = db.query(Session).filter(
                Session.account_id == account.id,
                Session.status == 'error'
            ).count()

            assert closed_sessions == 3

            # Check that one new session is created
            active_sessions = db.query(Session).filter(
                Session.account_id == account.id,
                Session.status == 'active'
            ).all()

            assert len(active_sessions) == 1
            assert active_sessions[0].source_ip == "10.0.0.100"


class TestGeoIPIntegration:
    """
    Tests for GeoIP integration.
    """

    def test_geoip_resolved_for_new_session(self, db):
        """
        GeoIP data is written to new session.
        """
        from collector.client_connect import client_connect
        from core.models import Account, Session

        # Create account
        account = Account(cn="geoip_user", serial_number="serial1")
        db.add(account)
        db.commit()

        env_vars = {
            'common_name': 'geoip_user',
            'serial_number': 'serial1',
            'trusted_ip': '8.8.8.8',
            'trusted_port': '22222'
        }

        geo_data = {'country': 'US', 'city': 'Mountain View'}

        with patch('collector.client_connect.get_env_vars', return_value=env_vars), \
             patch('collector.client_connect.resolve_geoip', return_value=geo_data):

            result = client_connect(db_session=db)

            assert result == 0

            # Check that GeoIP data is written
            session = db.query(Session).filter(
                Session.account_id == account.id,
                Session.status == 'active'
            ).first()

            assert session is not None
            assert session.country == 'US'
            assert session.city == 'Mountain View'
