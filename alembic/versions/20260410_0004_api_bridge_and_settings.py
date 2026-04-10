"""api bridge support and settings tables

Revision ID: 20260410_0004
Revises: 20260410_0003
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_0004"
down_revision = "20260410_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
    )
    op.create_index("ix_orders_priority", "orders", ["priority"])

    op.add_column("users", sa.Column("stage", sa.String(length=30), nullable=True))

    op.create_table(
        "glass_types",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )
    op.create_index("ix_glass_types_name", "glass_types", ["name"])

    op.create_table(
        "notification_templates",
        sa.Column("template_key", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )

    op.create_table(
        "email_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="preview"),
        sa.Column("transport", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
    )
    op.create_index("ix_email_logs_template_key", "email_logs", ["template_key"])
    op.create_index("ix_email_logs_customer_email", "email_logs", ["customer_email"])


def downgrade() -> None:
    op.drop_index("ix_email_logs_customer_email", table_name="email_logs")
    op.drop_index("ix_email_logs_template_key", table_name="email_logs")
    op.drop_table("email_logs")

    op.drop_table("notification_templates")

    op.drop_index("ix_glass_types_name", table_name="glass_types")
    op.drop_table("glass_types")

    op.drop_column("users", "stage")

    op.drop_index("ix_orders_priority", table_name="orders")
    op.drop_column("orders", "priority")
