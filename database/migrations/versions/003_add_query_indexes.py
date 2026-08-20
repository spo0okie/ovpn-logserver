"""
Добавление индексов под фактические запросы API и session_cleanup.

- connection_attempts.cert_cn: фильтр в /api/v1/attempts
  (Account.cn == x) OR (ConnectionAttempt.cert_cn == x) давал полный скан.
- sessions(status, connected_at): /sessions/active и session_cleanup
  фильтруют status='active' и сортируют по connected_at; одиночный idx_status
  малоселективен, композит убирает filesort.

Миграция аддитивна и безопасна для живой БД (MySQL 8 создаёт вторичные
индексы online, без простоя).

Revision ID: 003
Revises: 002
Create Date: 2026-08-20 00:00:00.000000
"""
from alembic import op

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('idx_cert_cn', 'connection_attempts', ['cert_cn'])
    op.create_index('idx_status_connected_at', 'sessions', ['status', 'connected_at'])


def downgrade() -> None:
    op.drop_index('idx_status_connected_at', table_name='sessions')
    op.drop_index('idx_cert_cn', table_name='connection_attempts')
