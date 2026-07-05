"""Common SQLAlchemy custom types and conventions."""

from decimal import Decimal

from sqlalchemy import Numeric

# Money type alias for Numeric(18,2)
# Using a type alias instead of TypeDecorator for Alembic compatibility.
# The value processing is handled at the repository/service layer.
Money = Numeric(18, 2)
