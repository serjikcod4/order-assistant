"""Add safe HTTP ERP observability metadata to submissions."""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0004_http_erp_metadata"
down_revision = "0003_llm_runtime_resilience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_submissions",
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "order_submissions",
        sa.Column(
            "erp_backend",
            sa.String(length=32),
            nullable=False,
            server_default="fake",
        ),
    )
    op.add_column(
        "order_submissions",
        sa.Column(
            "erp_provider",
            sa.String(length=64),
            nullable=False,
            server_default="in_memory",
        ),
    )
    op.add_column(
        "order_submissions",
        sa.Column(
            "erp_contract_version",
            sa.String(length=16),
            nullable=False,
            server_default="v1",
        ),
    )
    op.add_column(
        "order_submissions",
        sa.Column("last_http_status", sa.Integer(), nullable=True),
    )
    op.add_column(
        "order_submissions",
        sa.Column("normalized_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "order_submissions",
        sa.Column("erp_call_duration_ms", sa.Integer(), nullable=True),
    )

    submissions = sa.table(
        "order_submissions",
        sa.column("submission_id", sa.Uuid()),
        sa.column("correlation_id", sa.Uuid()),
    )
    connection = op.get_bind()
    for submission_id in connection.execute(
        sa.select(submissions.c.submission_id)
    ).scalars():
        connection.execute(
            submissions.update()
            .where(submissions.c.submission_id == submission_id)
            .values(correlation_id=uuid4())
        )
    with op.batch_alter_table("order_submissions") as batch:
        batch.alter_column("correlation_id", nullable=False)
        batch.alter_column("erp_backend", server_default=None)
        batch.alter_column("erp_provider", server_default=None)
        batch.alter_column("erp_contract_version", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("order_submissions") as batch:
        batch.drop_column("erp_call_duration_ms")
        batch.drop_column("normalized_error_code")
        batch.drop_column("last_http_status")
        batch.drop_column("erp_contract_version")
        batch.drop_column("erp_provider")
        batch.drop_column("erp_backend")
        batch.drop_column("correlation_id")
