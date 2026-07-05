"""Investment schema migration – investment_accounts, securities, trades, etc.

Revision ID: p22_investment
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p22_investment"
down_revision: Union[str, None] = "p19_budget"
branch_labels: Union[str, Sequence[str | None], None] = None
depends_on: Union[str, Sequence[str | None], None] = None


def upgrade() -> None:
    # investment_accounts
    op.create_table(
        "investment_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("linked_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("broker", sa.String(100), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="CNY"),
        sa.Column("initial_capital", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("module_status", sa.String(20), nullable=False, server_default="enabled"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # securities
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("market", sa.String(10), nullable=False, server_default="CN"),
        sa.Column("security_type", sa.String(20), nullable=False, server_default="stock"),
        sa.Column("industry", sa.String(50), nullable=True),
        sa.Column("is_listed", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # investment_trades
    op.create_table(
        "investment_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("investment_account_id", sa.Integer(), sa.ForeignKey("investment_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("trade_type", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 2), nullable=False),
        sa.Column("price", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # investment_cash_flows
    op.create_table(
        "investment_cash_flows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("investment_account_id", sa.Integer(), sa.ForeignKey("investment_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("investment_trades.id"), nullable=True),
        sa.Column("flow_date", sa.Date(), nullable=False),
        sa.Column("flow_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=True),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("investment_cash_flows")
    op.drop_table("investment_trades")
    op.drop_table("securities")
    op.drop_table("investment_accounts")
