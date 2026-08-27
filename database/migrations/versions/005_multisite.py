"""
Мультисайт: справочник серверов, привязка сессий к серверу, per-site статус CCD.

Контекст (docs/multisite.md): один центральный CA/админ-хост выпускает
сертификаты для нескольких OpenVPN-серверов на разных сайтах. Сессии и CCD
существуют на конкретном сервере, поэтому:

- vpn_servers — справочник инстансов OpenVPN (один инстанс = одна запись,
  2FA-инстанс на том же хосте регистрируется отдельно). Записи создаются
  автоматически collector'ом по имени из конфигурации.
- sessions.server_id — на каком сервере шла сессия. NULL допустим: это
  legacy-строки, созданные до мультисайта; они принадлежат единственному
  существовавшему тогда серверу.
- ccd_status — per-site наличие CCD: строка = (cn, server) — файл `<cn>` есть
  на этом сервере; нет строки — нет CCD (файлы `<cn>_OFF` — архив выключенного
  доступа, считаются отсутствием CCD). accounts.has_ccd при этом остаётся
  агрегатом «есть хотя бы на одном сервере» и пересчитывается ccd_checker'ом
  из ccd_status.

Revision ID: 005
Revises: 004
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vpn_servers',
        sa.Column('id', mysql.INTEGER(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False,
                  comment='Уникальное имя инстанса OpenVPN (chl, msk-2fa, ...)'),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uk_vpn_servers_name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )

    op.create_table(
        'ccd_status',
        sa.Column('id', mysql.INTEGER(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('cn', sa.String(length=255), nullable=False,
                  comment='Common Name / имя конфига'),
        sa.Column('server_id', mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column('ccd_updated_at', sa.DateTime(), nullable=True,
                  comment='mtime CCD-файла (naive UTC)'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['server_id'], ['vpn_servers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cn', 'server_id', name='uk_ccd_cn_server'),
        sa.Index('idx_ccd_cn', 'cn'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )

    op.add_column(
        'sessions',
        sa.Column('server_id', mysql.INTEGER(unsigned=True), nullable=True,
                  comment='Сервер сессии (NULL — legacy до мультисайта)'),
    )
    op.create_foreign_key(
        'fk_sessions_server_id', 'sessions', 'vpn_servers',
        ['server_id'], ['id'], ondelete='SET NULL',
    )
    # session_cleanup фильтрует по (server_id, status) на каждом запуске
    op.create_index('idx_server_id_status', 'sessions', ['server_id', 'status'])


def downgrade() -> None:
    op.drop_index('idx_server_id_status', table_name='sessions')
    op.drop_constraint('fk_sessions_server_id', 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'server_id')
    op.drop_table('ccd_status')
    op.drop_table('vpn_servers')
