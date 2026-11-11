"""Inquiry kind: purchase request or human handoff.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11

Existing inquiries are purchase requests, which is also the default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inquiries",
        sa.Column("kind", sa.String(length=32), server_default="purchase", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("inquiries", "kind")
