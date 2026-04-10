"""order pickup and drawing fields

Revision ID: 20260410_0002
Revises: 20260409_0001
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_0002"
down_revision = "20260409_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("pickup_approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("orders", sa.Column("pickup_approved_by", sa.String(length=36), nullable=True))
    op.add_column("orders", sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("picked_up_by", sa.String(length=36), nullable=True))
    op.add_column("orders", sa.Column("pickup_signer_name", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("pickup_signature_key", sa.String(length=500), nullable=True))
    op.add_column("orders", sa.Column("drawing_object_key", sa.String(length=500), nullable=True))
    op.add_column(
        "orders", sa.Column("drawing_original_name", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("orders", "drawing_original_name")
    op.drop_column("orders", "drawing_object_key")
    op.drop_column("orders", "pickup_signature_key")
    op.drop_column("orders", "pickup_signer_name")
    op.drop_column("orders", "picked_up_by")
    op.drop_column("orders", "picked_up_at")
    op.drop_column("orders", "pickup_approved_by")
    op.drop_column("orders", "pickup_approved_at")
