from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from .base import Base


class OrderDraftORM(Base):
    __tablename__ = "order_drafts"

    draft_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[str | None] = mapped_column(String(255))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_order_id: Mapped[str | None] = mapped_column(String(255))


class OrderSubmissionORM(Base):
    __tablename__ = "order_submissions"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_order_submissions_draft_id"),
        UniqueConstraint("idempotency_key", name="uq_order_submissions_idempotency_key"),
        Index("ix_order_submissions_status", "status"),
        Index("ix_order_submissions_updated_at", "updated_at"),
    )

    submission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    draft_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("order_drafts.draft_id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_order_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    erp_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    erp_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    erp_contract_version: Mapped[str] = mapped_column(String(16), nullable=False)
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    normalized_error_code: Mapped[str | None] = mapped_column(String(64))
    erp_call_duration_ms: Mapped[int | None] = mapped_column(Integer)


class ExtractionAuditORM(Base):
    __tablename__ = "extraction_audits"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_extraction_audits_request_id"),
        Index("ix_extraction_audits_created_at", "created_at"),
        Index("ix_extraction_audits_rollout_mode", "rollout_mode"),
    )

    audit_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    rollout_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    extractor_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    guard_version: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    grounding_issue_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    clarification_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_text_length: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    draft_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("order_drafts.draft_id")
    )
    llm_error_code: Mapped[str | None] = mapped_column(String(64))
    queue_wait_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inference_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_extraction_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    runtime_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    circuit_state_at_start: Mapped[str] = mapped_column(
        String(32), nullable=False, default="closed"
    )
    capacity_rejected: Mapped[bool] = mapped_column(nullable=False, default=False)
    queue_timed_out: Mapped[bool] = mapped_column(nullable=False, default=False)


class ExtractionReviewORM(Base):
    __tablename__ = "extraction_reviews"

    audit_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("extraction_audits.audit_id", ondelete="CASCADE"),
        primary_key=True,
    )
    reviewer_actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    corrected_order: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correction_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500))
