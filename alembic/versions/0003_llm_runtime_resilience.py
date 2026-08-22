"""Add bounded-runtime metrics to extraction audit records."""

from alembic import op
import sqlalchemy as sa


revision = "0003_llm_runtime_resilience"
down_revision = "0002_extraction_audits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction_audits",
        sa.Column("queue_wait_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extraction_audits",
        sa.Column("inference_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extraction_audits",
        sa.Column(
            "total_extraction_ms", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "extraction_audits",
        sa.Column(
            "runtime_attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "extraction_audits",
        sa.Column(
            "circuit_state_at_start",
            sa.String(length=32),
            nullable=False,
            server_default="closed",
        ),
    )
    op.add_column(
        "extraction_audits",
        sa.Column(
            "capacity_rejected", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "extraction_audits",
        sa.Column(
            "queue_timed_out", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("extraction_audits", "queue_timed_out")
    op.drop_column("extraction_audits", "capacity_rejected")
    op.drop_column("extraction_audits", "circuit_state_at_start")
    op.drop_column("extraction_audits", "runtime_attempt_count")
    op.drop_column("extraction_audits", "total_extraction_ms")
    op.drop_column("extraction_audits", "inference_ms")
    op.drop_column("extraction_audits", "queue_wait_ms")
