"""Add model capabilities and unit billing.

Revision ID: 0003_capabilities
Revises: 0002_routing_limits
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_capabilities"
down_revision: Union[str, Sequence[str], None] = "0002_routing_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("model_configs") as batch_op:
        batch_op.add_column(sa.Column("endpoint_type", sa.String(length=40), nullable=False, server_default="chat"))
        batch_op.add_column(sa.Column("unit_price", sa.Numeric(18, 6), nullable=False, server_default="0"))
    with op.batch_alter_table("model_routes") as batch_op:
        batch_op.add_column(sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False, server_default="0"))
    with op.batch_alter_table("usage_logs") as batch_op:
        batch_op.add_column(sa.Column("endpoint", sa.String(length=40), nullable=False, server_default="chat.completions"))
        batch_op.add_column(sa.Column("units", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("usage_logs") as batch_op:
        batch_op.drop_column("units")
        batch_op.drop_column("endpoint")
    with op.batch_alter_table("model_routes") as batch_op:
        batch_op.drop_column("unit_cost")
    with op.batch_alter_table("model_configs") as batch_op:
        batch_op.drop_column("unit_price")
        batch_op.drop_column("endpoint_type")
