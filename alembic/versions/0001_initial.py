"""Initial order persistence tables."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_drafts",
        sa.Column("draft_id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("processing_result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(length=255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_by", sa.String(length=255)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("created_order_id", sa.String(length=255)),
    )
    op.create_table(
        "order_submissions",
        sa.Column("submission_id", sa.Uuid(), primary_key=True),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("order_drafts.draft_id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_order_id", sa.String(length=255)),
        sa.Column("last_error", sa.Text()),
        sa.UniqueConstraint("draft_id", name="uq_order_submissions_draft_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_order_submissions_idempotency_key"),
    )
    op.create_index("ix_order_submissions_status", "order_submissions", ["status"])
    op.create_index("ix_order_submissions_updated_at", "order_submissions", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_order_submissions_updated_at", table_name="order_submissions")
    op.drop_index("ix_order_submissions_status", table_name="order_submissions")
    op.drop_table("order_submissions")
    op.drop_table("order_drafts")
