"""Receivable schema

Revision ID: abc123def456
Revises: fc0dafc40faf
Create Date: 2026-07-05 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'abc123def456'
down_revision: Union[str, Sequence[str], None] = 'fc0dafc40faf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'receivable_cases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('debtor', sa.String(length=200), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('recovered_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('written_off_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('occurrence_date', sa.Date(), nullable=False),
        sa.Column('import_job_id', sa.Integer(), sa.ForeignKey('import_jobs.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'receivable_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('receivable_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transactions.id'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('receivable_events')
    op.drop_table('receivable_cases')
