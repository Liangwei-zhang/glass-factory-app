"""user identity channels and work-order step fields

Revision ID: 20260410_0003
Revises: 20260410_0002
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_0003"
down_revision = "20260410_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("whatsapp_id", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("wechat_id", sa.String(length=64), nullable=True))
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
    op.create_index("ix_users_whatsapp_id", "users", ["whatsapp_id"], unique=True)
    op.create_index("ix_users_wechat_id", "users", ["wechat_id"], unique=True)

    op.add_column(
        "work_orders",
        sa.Column(
            "assigned_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "work_orders",
        sa.Column(
            "process_step_key",
            sa.String(length=30),
            nullable=False,
            server_default="cutting",
        ),
    )
    op.add_column(
        "work_orders",
        sa.Column(
            "rework_unread",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_work_orders_assigned_user_id", "work_orders", ["assigned_user_id"])
    op.create_index("ix_work_orders_process_step_key", "work_orders", ["process_step_key"])


def downgrade() -> None:
    op.drop_index("ix_work_orders_process_step_key", table_name="work_orders")
    op.drop_index("ix_work_orders_assigned_user_id", table_name="work_orders")
    op.drop_column("work_orders", "rework_unread")
    op.drop_column("work_orders", "process_step_key")
    op.drop_column("work_orders", "assigned_user_id")

    op.drop_index("ix_users_wechat_id", table_name="users")
    op.drop_index("ix_users_whatsapp_id", table_name="users")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_column("users", "wechat_id")
    op.drop_column("users", "whatsapp_id")
    op.drop_column("users", "phone")
