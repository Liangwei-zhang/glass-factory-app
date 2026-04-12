"""initial schema

Revision ID: 20260409_0001
Revises:
Create Date: 2026-04-09
"""

from __future__ import annotations

from alembic import op
from infra.db import models as _models  # noqa: F401
from infra.db.base import Base

# revision identifiers, used by Alembic.
revision = "20260409_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
