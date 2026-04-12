"""inventory reservation ledger

Revision ID: 20260410_0006
Revises: 20260410_0005
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_0006"
down_revision = "20260410_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("order_no", sa.String(length=30), nullable=False),
        sa.Column("reserved_qty", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_reservations_product_id",
        "inventory_reservations",
        ["product_id"],
    )
    op.create_index(
        "ix_inventory_reservations_order_id",
        "inventory_reservations",
        ["order_id"],
    )
    op.create_index(
        "ix_inventory_reservations_order_no",
        "inventory_reservations",
        ["order_no"],
    )
    op.create_index(
        "ix_inventory_reservations_status",
        "inventory_reservations",
        ["status"],
    )
    op.create_index(
        "ix_inventory_reservations_expires_at",
        "inventory_reservations",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_reservations_expires_at", table_name="inventory_reservations")
    op.drop_index("ix_inventory_reservations_status", table_name="inventory_reservations")
    op.drop_index("ix_inventory_reservations_order_no", table_name="inventory_reservations")
    op.drop_index("ix_inventory_reservations_order_id", table_name="inventory_reservations")
    op.drop_index("ix_inventory_reservations_product_id", table_name="inventory_reservations")
    op.drop_table("inventory_reservations")
