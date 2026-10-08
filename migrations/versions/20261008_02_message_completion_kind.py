"""Persist assistant message completion kinds.

Revision ID: 20261008_02
Revises: 20261004_01
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261008_02"
down_revision: str | None = "20261004_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("completion_kind", sa.String(32), nullable=True))
    op.execute(
        sa.text(
            "UPDATE messages SET completion_kind = "
            "CASE WHEN grounded THEN 'answer' ELSE 'clarification' END "
            "WHERE role = 'assistant' AND status = 'completed'"
        )
    )


def downgrade() -> None:
    op.drop_column("messages", "completion_kind")
