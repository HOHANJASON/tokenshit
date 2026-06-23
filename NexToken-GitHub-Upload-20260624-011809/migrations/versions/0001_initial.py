"""Initial NexToken schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customers_email"), "customers", ["email"], unique=True)
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_keys_customer_id"), "api_keys", ["customer_id"], unique=False)
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"], unique=False)
    op.create_table(
        "ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ledger_customer_id"), "ledger", ["customer_id"], unique=False)
    op.create_table(
        "model_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_name", sa.String(length=160), nullable=False),
        sa.Column("upstream_model", sa.String(length=200), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("input_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("output_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("input_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("output_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_model_configs_public_name"), "model_configs", ["public_name"], unique=True)
    op.create_table(
        "usage_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("upstream_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("charge", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usage_logs_api_key_id"), "usage_logs", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_usage_logs_customer_id"), "usage_logs", ["customer_id"], unique=False)
    op.create_index(op.f("ix_usage_logs_model"), "usage_logs", ["model"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_logs_model"), table_name="usage_logs")
    op.drop_index(op.f("ix_usage_logs_customer_id"), table_name="usage_logs")
    op.drop_index(op.f("ix_usage_logs_api_key_id"), table_name="usage_logs")
    op.drop_table("usage_logs")
    op.drop_index(op.f("ix_model_configs_public_name"), table_name="model_configs")
    op.drop_table("model_configs")
    op.drop_index(op.f("ix_ledger_customer_id"), table_name="ledger")
    op.drop_table("ledger")
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_customer_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("providers")
    op.drop_index(op.f("ix_customers_email"), table_name="customers")
    op.drop_table("customers")
