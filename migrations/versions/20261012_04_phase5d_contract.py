"""Complete Phase 5D versioning and citation contract.

Revision ID: 20261012_04
Revises: 20261011_03
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_04"
down_revision: str | None = "20261011_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tax_intake_sessions",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "tax_intake_sessions",
        sa.Column("answer_updated_at", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "message_citations",
        sa.Column("claim_type", sa.String(100), nullable=False, server_default="salary_wages"),
    )
    with op.batch_alter_table("tax_intake_sessions") as batch_op:
        batch_op.drop_constraint("ck_tax_intake_workflow_status", type_="check")
        batch_op.create_check_constraint(
            "ck_tax_intake_workflow_status",
            "workflow_status IN ('questionnaire_active', 'questionnaire_completed', "
            "'retrieving_documents', 'checklist_ready', 'awaiting_summary_confirmation', "
            "'summary_declined', 'generating_summary', 'summary_completed', "
            "'cancelled', 'failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("tax_intake_sessions") as batch_op:
        batch_op.drop_constraint("ck_tax_intake_workflow_status", type_="check")
        batch_op.create_check_constraint(
            "ck_tax_intake_workflow_status",
            "workflow_status IN ('questionnaire_active', 'questionnaire_completed', "
            "'retrieving_documents', 'checklist_ready', 'awaiting_summary_confirmation', "
            "'summary_declined', 'generating_summary', 'summary_completed')",
        )
    op.drop_column("message_citations", "claim_type")
    op.drop_column("tax_intake_sessions", "answer_updated_at")
    op.drop_column("tax_intake_sessions", "version")
