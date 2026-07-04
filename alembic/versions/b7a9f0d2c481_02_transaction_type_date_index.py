# ruff: noqa
"""02_transaction_type_date_index

Revision ID: b7a9f0d2c481
Revises: 81c53c9ecdc7
Create Date: 2026-07-04 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7a9f0d2c481'
down_revision: Union[str, Sequence[str], None] = '81c53c9ecdc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'ix_trans_type_date',
        'transactions',
        ['type', 'transaction_date'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_trans_type_date', table_name='transactions')
