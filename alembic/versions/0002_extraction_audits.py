"""Add privacy-aware extraction audits and human reviews."""

from alembic import op
import sqlalchemy as sa


revision = "0002_extraction_audits"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_audits",
        sa.Column("audit_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rollout_mode", sa.String(length=32), nullable=False),
        sa.Column("extractor_backend", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("guard_version", sa.String(length=64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("processing_outcome", sa.String(length=64), nullable=False),
        sa.Column("grounding_issue_codes", sa.JSON(), nullable=False),
        sa.Column("clarification_codes", sa.JSON(), nullable=False),
        sa.Column("source_text_length", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "draft_id",
            sa.Uuid(),
            sa.ForeignKey("order_drafts.draft_id"),
        ),
        sa.Column("llm_error_code", sa.String(length=64)),
        sa.UniqueConstraint("request_id", name="uq_extraction_audits_request_id"),
    )
    op.create_index(
        "ix_extraction_audits_created_at",
        "extraction_audits",
        ["created_at"],
    )
    op.create_index(
        "ix_extraction_audits_rollout_mode",
        "extraction_audits",
        ["rollout_mode"],
    )
    op.create_table(
        "extraction_reviews",
        sa.Column(
            "audit_id",
            sa.Uuid(),
            sa.ForeignKey("extraction_audits.audit_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("reviewer_actor_id", sa.String(length=255), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("corrected_order", sa.JSON()),
        sa.Column("correction_codes", sa.JSON(), nullable=False),
        sa.Column("comment", sa.String(length=500)),
    )


def downgrade() -> None:
    op.drop_table("extraction_reviews")
    op.drop_index("ix_extraction_audits_rollout_mode", table_name="extraction_audits")
    op.drop_index("ix_extraction_audits_created_at", table_name="extraction_audits")
    op.drop_table("extraction_audits")
