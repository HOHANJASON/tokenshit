"""Add provider routes and API key rate limits.

Revision ID: 0002_routing_limits
Revises: 0001_initial
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_routing_limits"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(sa.Column("rpm_limit", sa.Integer(), nullable=False, server_default="60"))
        batch_op.add_column(sa.Column("tpm_limit", sa.Integer(), nullable=False, server_default="100000"))

    op.create_table(
        "model_routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_config_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("upstream_model", sa.String(length=200), nullable=False),
        sa.Column("input_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("output_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("disabled_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_config_id"], ["model_configs.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_config_id", "provider_id", "upstream_model", name="uq_model_route"),
    )
    op.create_index(op.f("ix_model_routes_model_config_id"), "model_routes", ["model_config_id"], unique=False)
    op.create_index(op.f("ix_model_routes_provider_id"), "model_routes", ["provider_id"], unique=False)
    op.execute(
        sa.text(
            """
            INSERT INTO model_routes
                (model_config_id, provider_id, upstream_model, input_cost, output_cost,
                 priority, weight, active, failure_count, created_at, updated_at)
            SELECT id, provider_id, upstream_model, input_cost, output_cost,
                   10, 100, active, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM model_configs
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_routes_provider_id"), table_name="model_routes")
    op.drop_index(op.f("ix_model_routes_model_config_id"), table_name="model_routes")
    op.drop_table("model_routes")
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("tpm_limit")
        batch_op.drop_column("rpm_limit")
