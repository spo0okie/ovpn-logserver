"""
Миграция для добавления поддержки нескольких сертификатов на одного пользователя.

Добавляет поле serial_number в таблицу accounts и обновляет constraints.

Revision ID: 002
Revises: 001
Create Date: 2026-02-02 04:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Добавление поля serial_number и обновление constraints.

    1. Добавляет колонку serial_number VARCHAR(64) nullable
    2. Заполняет существующие записи значением CONCAT('legacy_', id)
    3. Делает колонку NOT NULL
    4. Удаляет старый constraint uk_cn
    5. Создает новый composite unique constraint uk_cn_serial (cn, serial_number)
    6. Создает индексы idx_cn и idx_serial_number
    """
    # 1. Добавляем колонку serial_number как nullable
    op.add_column(
        'accounts',
        sa.Column(
            'serial_number',
            sa.String(length=64),
            nullable=True,
            comment='Серийный номер сертификата'
        )
    )

    # 2. Заполняем существующие записи значением CONCAT('legacy_', id)
    # Это гарантирует уникальность для существующих записей
    op.execute("UPDATE accounts SET serial_number = CONCAT('legacy_', id)")

    # 3. Делаем колонку NOT NULL
    op.alter_column(
        'accounts',
        'serial_number',
        existing_type=sa.String(length=64),
        nullable=False
    )

    # 4. Удаляем старый unique constraint uk_cn
    op.drop_constraint('uk_cn', 'accounts', type_='unique')

    # 5. Создаем новый composite unique constraint
    op.create_unique_constraint(
        'uk_cn_serial',
        'accounts',
        ['cn', 'serial_number']
    )

    # 6. Создаем индексы для быстрого поиска
    op.create_index(
        'idx_cn',
        'accounts',
        ['cn']
    )
    op.create_index(
        'idx_serial_number',
        'accounts',
        ['serial_number']
    )


def downgrade() -> None:
    """
    Откат миграции - возврат к уникальности по CN.

    Удаляет поле serial_number и восстанавливает старый constraint.
    """
    # Удаляем индексы
    op.drop_index('idx_serial_number', table_name='accounts')
    op.drop_index('idx_cn', table_name='accounts')

    # Удаляем новый composite constraint
    op.drop_constraint('uk_cn_serial', 'accounts', type_='unique')

    # Восстанавливаем старый unique constraint
    # Примечание: может не сработать если есть дубликаты CN
    op.create_unique_constraint(
        'uk_cn',
        'accounts',
        ['cn']
    )

    # Удаляем колонку serial_number
    op.drop_column('accounts', 'serial_number')
