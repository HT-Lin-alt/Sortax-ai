"""Create chat and RAG persistence tables.

Revision ID: 20261004_01
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261004_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RUN_STATUSES = "'pending', 'streaming', 'completed', 'failed', 'cancelled'"


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_conversations_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_index("ix_conversations_owner_user_id", "conversations", ["owner_user_id"])
    op.create_index(
        "ix_conversations_owner_last_message",
        "conversations",
        ["tenant_id", "owner_user_id", "last_message_at", "id"],
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("client_message_id", sa.Uuid()),
        sa.Column("parent_message_id", sa.Uuid()),
        sa.Column("retry_of_message_id", sa.Uuid()),
        sa.Column("model_provider", sa.String(100)),
        sa.Column("model_name", sa.String(200)),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("retrieval_run_id", sa.Uuid()),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_messages_role"),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_messages_status"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["retry_of_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "author_user_id", "client_message_id", name="uq_messages_idempotency"
        ),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_retrieval_run_id", "messages", ["retrieval_run_id"])
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["tenant_id", "conversation_id", "created_at", "id"],
    )

    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(100), nullable=False),
        sa.Column("claim_type", sa.String(100)),
        sa.Column("tax_year", sa.String(7)),
        sa.Column("query_hash", sa.String(128), nullable=False),
        sa.Column("embedding_provider", sa.String(100), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("retrieval_config_version", sa.String(100), nullable=False),
        sa.Column("collection_name", sa.String(200), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("score_threshold", sa.Numeric(8, 6), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(200)),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_retrieval_runs_status"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retrieval_runs_tenant_id", "retrieval_runs", ["tenant_id"])
    op.create_index(
        "ix_retrieval_runs_conversation",
        "retrieval_runs",
        ["tenant_id", "conversation_id", "started_at"],
    )

    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_run_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_token_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("provider_request_id", sa.String(200)),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(200)),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_generation_runs_status"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["retrieval_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generation_runs_tenant_id", "generation_runs", ["tenant_id"])
    op.create_index(
        "ix_generation_runs_conversation",
        "generation_runs",
        ["tenant_id", "conversation_id", "started_at"],
    )

    op.create_table(
        "message_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("chunk_ids", sa.JSON(), nullable=False),
        sa.Column("title_snapshot", sa.String(500), nullable=False),
        sa.Column("url_snapshot", sa.Text(), nullable=False),
        sa.Column("section_snapshot", sa.String(500)),
        sa.Column("tax_years_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_accessed_at", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["retrieval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "message_id", "ordinal", name="uq_message_citations_ordinal"
        ),
    )
    op.create_index("ix_message_citations_tenant_id", "message_citations", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("message_citations")
    op.drop_table("generation_runs")
    op.drop_table("retrieval_runs")
    op.drop_table("messages")
    op.drop_table("conversations")
