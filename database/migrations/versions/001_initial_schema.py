"""
Начальная схема базы данных OpenVPN Log Server.

Создаёт таблицы:
- accounts: справочник аккаунтов OpenVPN
- sessions: журнал VPN сессий
- connection_attempts: неудачные попытки подключения
- geoip_cache: кэш GeoIP данных

Revision ID: 001
Revises:
Create Date: 2026-01-31 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Создание начальной схемы базы данных.

    Создаёт все необходимые таблицы с индексами и внешними ключами.
    """
    # Таблица accounts - справочник аккаунтов OpenVPN
    op.create_table(
        'accounts',
        sa.Column('id', mysql.INTEGER(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('cn', sa.String(length=255), nullable=False, comment='Common Name сертификата'),
        sa.Column('valid_from', sa.DateTime(), nullable=True, comment='Срок начала действия сертификата'),
        sa.Column('valid_to', sa.DateTime(), nullable=True, comment='Срок окончания действия сертификата'),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default=sa.text('0'), comment='Отозван по CRL'),
        sa.Column('revoked_at', sa.DateTime(), nullable=True, comment='Дата отзыва (из CRL)'),
        sa.Column('has_ccd', sa.Boolean(), nullable=False, server_default=sa.text('0'), comment='Наличие CCD файла'),
        sa.Column('ccd_updated_at', sa.DateTime(), nullable=True, comment='Дата последней проверки CCD'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cn', name='uk_cn'),
        sa.Index('idx_valid_to', 'valid_to'),
        sa.Index('idx_is_revoked', 'is_revoked'),
        sa.Index('idx_has_ccd', 'has_ccd'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
        comment='Справочник аккаунтов OpenVPN'
    )

    # Таблица sessions - журнал VPN сессий
    op.create_table(
        'sessions',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('account_id', mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column('session_id', sa.String(length=100), nullable=True, comment='Внутренний ID сессии OpenVPN'),
        sa.Column('connected_at', sa.DateTime(), nullable=False, comment='Время подключения'),
        sa.Column('disconnected_at', sa.DateTime(), nullable=True, comment='Время отключения (NULL = активна)'),
        sa.Column('source_ip', sa.String(length=45), nullable=False, comment='IP источника (IPv4/IPv6)'),
        sa.Column('country', sa.String(length=100), nullable=True, comment='Страна по GeoIP'),
        sa.Column('city', sa.String(length=100), nullable=True, comment='Город по GeoIP'),
        sa.Column('bytes_sent', mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text('0'), comment='Отправлено байт'),
        sa.Column('bytes_received', mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text('0'), comment='Получено байт'),
        sa.Column('virtual_ip', sa.String(length=45), nullable=True, comment='Выделенный VPN IP клиента'),
        sa.Column(
            'status',
            sa.Enum('active', 'closed', 'error', name='session_status'),
            nullable=False,
            server_default='active'
        ),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.Index('idx_account_id', 'account_id'),
        sa.Index('idx_connected_at', 'connected_at'),
        sa.Index('idx_disconnected_at', 'disconnected_at'),
        sa.Index('idx_status', 'status'),
        sa.Index('idx_source_ip', 'source_ip'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
        comment='Журнал VPN сессий'
    )

    # Таблица connection_attempts - неудачные попытки подключения
    op.create_table(
        'connection_attempts',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('account_id', mysql.INTEGER(unsigned=True), nullable=True, comment='ID аккаунта (NULL если не удалось определить)'),
        sa.Column('attempted_at', sa.DateTime(), nullable=False, comment='Время попытки'),
        sa.Column('source_ip', sa.String(length=45), nullable=False, comment='IP источника'),
        sa.Column('cert_cn', sa.String(length=255), nullable=True, comment='CN из предъявленного сертификата'),
        sa.Column('failure_reason', sa.String(length=255), nullable=False, comment='Причина отказа'),
        sa.Column(
            'failure_type',
            sa.Enum('auth_failed', 'cert_revoked', 'cert_expired', 'ccd_missing', 'tls_error', 'other', name='failure_type'),
            nullable=False,
            server_default='other'
        ),
        sa.Column('details', sa.Text(), nullable=True, comment='Дополнительные детали ошибки'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.Index('idx_account_id', 'account_id'),
        sa.Index('idx_attempted_at', 'attempted_at'),
        sa.Index('idx_source_ip', 'source_ip'),
        sa.Index('idx_failure_type', 'failure_type'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
        comment='Неудачные попытки подключения'
    )

    # Таблица geoip_cache - кэш GeoIP данных
    op.create_table(
        'geoip_cache',
        sa.Column('ip', sa.String(length=45), nullable=False, comment='IP адрес'),
        sa.Column('country', sa.String(length=100), nullable=True, comment='Страна'),
        sa.Column('country_code', sa.String(length=2), nullable=True, comment='Код страны ISO'),
        sa.Column('city', sa.String(length=100), nullable=True, comment='Город'),
        sa.Column('region', sa.String(length=100), nullable=True, comment='Регион/область'),
        sa.Column('latitude', sa.DECIMAL(precision=10, scale=8), nullable=True, comment='Широта'),
        sa.Column('longitude', sa.DECIMAL(precision=11, scale=8), nullable=True, comment='Долгота'),
        sa.Column('isp', sa.String(length=255), nullable=True, comment='Провайдер'),
        sa.Column('cached_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('expires_at', sa.DateTime(), nullable=True, comment='Срок действия кэша'),
        sa.PrimaryKeyConstraint('ip'),
        sa.Index('idx_cached_at', 'cached_at'),
        sa.Index('idx_expires_at', 'expires_at'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
        comment='Кэш GeoIP данных'
    )


def downgrade() -> None:
    """
    Откат миграции - удаление всех созданных таблиц.

    Удаляет таблицы в обратном порядке создания для соблюдения
    целостности внешних ключей.
    """
    # Удаляем таблицы в обратном порядке (сначала дочерние)
    op.drop_table('geoip_cache')
    op.drop_table('connection_attempts')
    op.drop_table('sessions')
    op.drop_table('accounts')

    # Удаляем ENUM типы (для MySQL)
    op.execute("DROP TYPE IF EXISTS session_status")
    op.execute("DROP TYPE IF EXISTS failure_type")
