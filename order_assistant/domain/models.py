from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    ActorRole,
    Brand,
    CircuitState,
    DraftStatus,
    ExtractionCorrectionCode,
    ExtractionProcessingOutcome,
    ExtractionReviewDecision,
    GroundingIssueCode,
    LLMRolloutMode,
    OrderProcessingStatus,
    RejectionReason,
    SubmissionStatus,
)


class Actor(BaseModel):
    actor_id: str = Field(min_length=1)
    role: ActorRole

    @field_validator("actor_id")
    @classmethod
    def require_actor_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor_id cannot be empty.")
        return value


class RejectionDetail(BaseModel):
    code: RejectionReason
    actual: str
    expected: str


class OrderRequirements(BaseModel):
    model: str
    quantity: int = Field(gt=0)
    primary_brand: Brand
    fallback_brands: list[Brand]
    max_unit_price: Decimal = Field(gt=0)
    delivery_deadline: datetime
    allow_split_fulfillment: bool = False


class InventoryItem(BaseModel):
    sku: str
    brand: Brand
    model: str
    stock: int = Field(ge=0)
    unit_price: Decimal = Field(gt=0)
    delivery_available_at: datetime


class EvaluationResult(BaseModel):
    item: InventoryItem
    accepted: bool
    reasons: list[RejectionDetail]


class ExtractedOrder(BaseModel):
    model: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    primary_brand: Brand | None = None
    fallback_brands: list[Brand] = Field(default_factory=list)
    max_unit_price: Decimal | None = Field(default=None, gt=0)
    delivery_deadline: datetime | None = None
    allow_split_fulfillment: bool = False
    requires_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)


class ExtractionOutcome(BaseModel):
    requirements: OrderRequirements | None
    requires_clarification: bool
    clarification_questions: list[str]


class GroundingIssue(BaseModel):
    code: GroundingIssueCode
    field: str | None = None
    actual: str | None = None
    expected: str | None = None


class GroundingResult(BaseModel):
    extracted: ExtractedOrder
    issues: list[GroundingIssue]
    changed: bool


class ExtractionAuditRecord(BaseModel):
    audit_id: UUID
    request_id: UUID
    created_at: datetime
    rollout_mode: LLMRolloutMode
    extractor_backend: str
    model_name: str
    prompt_version: str
    guard_version: str
    latency_ms: int = Field(ge=0)
    processing_outcome: ExtractionProcessingOutcome
    grounding_issue_codes: list[GroundingIssueCode] = Field(default_factory=list)
    clarification_codes: list[GroundingIssueCode] = Field(default_factory=list)
    source_text_length: int = Field(ge=0)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_id: UUID | None = None
    llm_error_code: str | None = None
    queue_wait_ms: int = Field(default=0, ge=0)
    inference_ms: int = Field(default=0, ge=0)
    total_extraction_ms: int = Field(default=0, ge=0)
    runtime_attempt_count: int = Field(default=0, ge=0)
    circuit_state_at_start: CircuitState = CircuitState.CLOSED
    capacity_rejected: bool = False
    queue_timed_out: bool = False

    @field_validator("created_at")
    @classmethod
    def require_created_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Audit timestamp must be timezone-aware.")
        return value


class ExtractionReview(BaseModel):
    audit_id: UUID
    reviewer_actor_id: str = Field(min_length=1, max_length=255)
    reviewed_at: datetime
    decision: ExtractionReviewDecision
    corrected_order: ExtractedOrder | None = None
    correction_codes: list[ExtractionCorrectionCode] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("reviewed_at")
    @classmethod
    def require_reviewed_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Review timestamp must be timezone-aware.")
        return value

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_correction(self) -> "ExtractionReview":
        corrected = self.decision == ExtractionReviewDecision.CORRECTED
        if corrected and self.corrected_order is None:
            raise ValueError("corrected_order is required for corrected review.")
        if corrected and not self.correction_codes:
            raise ValueError("correction_codes are required for corrected review.")
        if not corrected and self.corrected_order is not None:
            raise ValueError("corrected_order is only allowed for corrected review.")
        if not corrected and self.correction_codes:
            raise ValueError("correction_codes are only allowed for corrected review.")
        return self


class OrderProcessingResult(BaseModel):
    status: OrderProcessingStatus
    requirements: OrderRequirements | None
    selected_item: InventoryItem | None
    evaluations: list[EvaluationResult]
    clarification_questions: list[str]
    total_price: Decimal | None
    requires_human_approval: bool


class OrderDraft(BaseModel):
    draft_id: UUID
    status: DraftStatus
    processing_result: OrderProcessingResult
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    created_order_id: str | None = None

    @field_validator("created_at", "approved_at", "rejected_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("Draft timestamps must be timezone-aware.")
        return value


class CreatedOrder(BaseModel):
    order_id: str
    draft_id: UUID
    sku: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    idempotency_key: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Order timestamp must be timezone-aware.")
        return value


class OrderSubmission(BaseModel):
    submission_id: UUID
    draft_id: UUID
    idempotency_key: str
    status: SubmissionStatus
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    created_order_id: str | None
    last_error: str | None
    correlation_id: UUID = Field(default_factory=uuid4)
    erp_backend: str = "fake"
    erp_provider: str = "in_memory"
    erp_contract_version: str = "v1"
    last_http_status: int | None = None
    normalized_error_code: str | None = None
    erp_call_duration_ms: int | None = Field(default=None, ge=0)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Submission timestamps must be timezone-aware UTC.")
        return value
