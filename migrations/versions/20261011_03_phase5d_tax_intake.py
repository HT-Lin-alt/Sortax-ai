"""Add Phase 5D tax intake and structured message persistence.

Revision ID: 20261011_03
Revises: 20261008_02
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_03"
down_revision: str | None = "20261008_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("content_type", sa.String(32), nullable=False, server_default="text"),
    )
    op.add_column("messages", sa.Column("structured_content", sa.JSON(), nullable=True))
    op.add_column("retrieval_runs", sa.Column("claim_types", sa.JSON(), nullable=True))

    op.create_table(
        "tax_intake_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.String(100), nullable=False),
        sa.Column("tax_year", sa.String(7), nullable=False),
        sa.Column("workflow_status", sa.String(40), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("summary_requested", sa.Boolean()),
        sa.Column("checklist_message_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "workflow_status IN ('questionnaire_active', 'questionnaire_completed', "
            "'retrieving_documents', 'checklist_ready', 'awaiting_summary_confirmation', "
            "'summary_declined', 'generating_summary', 'summary_completed')",
            name="ck_tax_intake_workflow_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["checklist_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "conversation_id", name="uq_tax_intake_conversation"),
    )
    op.create_index("ix_tax_intake_sessions_tenant_id", "tax_intake_sessions", ["tenant_id"])
    op.create_index(
        "ix_tax_intake_owner_conversation",
        "tax_intake_sessions",
        ["tenant_id", "owner_user_id", "conversation_id"],
    )

    op.create_table(
        "message_checklist_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("claim_type", sa.String(100), nullable=False),
        sa.Column("document_name", sa.String(500), nullable=False),
        sa.Column("plain_language_explanation", sa.Text(), nullable=False),
        sa.Column("how_to_obtain", sa.Text(), nullable=False),
        sa.Column("applies_because", sa.Text(), nullable=False),
        sa.Column("citation_ordinals", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "message_id", "ordinal", name="uq_message_checklist_items_ordinal"
        ),
    )
    op.create_index(
        "ix_message_checklist_items_tenant_id", "message_checklist_items", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("message_checklist_items")
    op.drop_table("tax_intake_sessions")
    op.drop_column("retrieval_runs", "claim_types")
    op.drop_column("messages", "structured_content")
    op.drop_column("messages", "content_type")
