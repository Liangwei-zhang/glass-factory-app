"""customer portal identity bridge

Revision ID: 20260410_0005
Revises: 20260410_0004
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_0005"
down_revision = "20260410_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("customer_id", sa.String(length=36), nullable=True))
    op.create_index("ix_users_customer_id", "users", ["customer_id"])
    op.create_foreign_key(
        "fk_users_customer_id_customers",
        "users",
        "customers",
        ["customer_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_customer_id_customers", "users", type_="foreignkey")
    op.drop_index("ix_users_customer_id", table_name="users")
    op.drop_column("users", "customer_id")