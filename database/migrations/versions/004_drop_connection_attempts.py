"""
Удаление таблицы connection_attempts.

Функция учёта неудачных попыток не была реализована: в таблицу не писал ни один
компонент, страница и API всегда возвращали пустой список. Каркас удалён из кода,
таблица удаляется здесь. Обоснование и работоспособный подход на будущее —
docs/connection-attempts.md.

ВНИМАНИЕ перед применением на проде: убедиться, что таблица действительно пуста.
    SELECT COUNT(*) FROM connection_attempts;
Ожидается 0. Если строки есть — значит появился неизвестный писатель, и миграцию
применять нельзя без разбирательства.

Revision ID: 004
Revises: 003
Create Date: 2026-08-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('connection_attempts')


def downgrade() -> None:
    """Восстанавливает пустую таблицу в виде из миграций 001 + 003."""
    op.create_table(
        'connection_attempts',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('account_id', mysql.INTEGER(unsigned=True), nullable=True,
                  comment='ID аккаунта (NULL если не удалось определить)'),
        sa.Column('attempted_at', sa.DateTime(), nullable=False, comment='Время попытки'),
        sa.Column('source_ip', sa.String(length=45), nullable=False, comment='IP источника'),
        sa.Column('cert_cn', sa.String(length=255), nullable=True,
                  comment='CN из предъявленного сертификата'),
        sa.Column('failure_reason', sa.String(length=255), nullable=False, comment='Причина отказа'),
        sa.Column(
            'failure_type',
            sa.Enum('auth_failed', 'cert_revoked', 'cert_expired', 'ccd_missing',
                    'tls_error', 'other', name='failure_type'),
            nullable=False, server_default='other',
        ),
        sa.Column('details', sa.Text(), nullable=True, comment='Дополнительные детали ошибки'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('idx_account_id', 'account_id'),
        sa.Index('idx_attempted_at', 'attempted_at'),
        sa.Index('idx_source_ip', 'source_ip'),
        sa.Index('idx_failure_type', 'failure_type'),
        sa.Index('idx_cert_cn', 'cert_cn'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )
