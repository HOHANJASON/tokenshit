"""add gmail identity fields

Revision ID: 0004_gmail_identity
Revises: 0003_capabilities
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_gmail_identity"
down_revision = "0003_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("google_email", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("google_picture", sa.String(length=500), nullable=True))
    op.add_column("customers", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("customers", sa.Column("gmail_bound_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_customers_google_sub"), "customers", ["google_sub"], unique=True)
    op.create_index(op.f("ix_customers_google_email"), "customers", ["google_email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_customers_google_email"), table_name="customers")
    op.drop_index(op.f("ix_customers_google_sub"), table_name="customers")
    op.drop_column("customers", "gmail_bound_at")
    op.drop_column("customers", "email_verified")
    op.drop_column("customers", "google_picture")
    op.drop_column("customers", "google_email")
    op.drop_column("customers", "google_sub")
