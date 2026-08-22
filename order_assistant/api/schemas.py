from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from order_assistant.domain import (
    ExtractedOrder,
    ExtractionAuditRecord,
    ExtractionCorrectionCode,
    ExtractionReview,
    ExtractionReviewDecision,
    GroundingIssue,
    OrderProcessingResult,
)


class HealthResponse(BaseModel):
    status: str = "ok"


class ReadinessResponse(BaseModel):
    status: str
    details: dict[str, object]


class OrderRequestResponse(BaseModel):
    """Workflow result plus a draft only when human approval is possible."""

    processing: OrderProcessingResult
    draft_id: UUID | None = None


class TextOrderRequest(BaseModel):
    """Free-form order text sent to the configured local extractor."""

    text: str = Field(min_length=1)


class TextOrderRequestResponse(BaseModel):
    status: str
    request_id: UUID
    audit_id: UUID
    guarded_result: ExtractedOrder
    grounding_issues: list[GroundingIssue] = Field(default_factory=list)
    processing: OrderProcessingResult | None = None
    draft_id: UUID | None = None


class ExtractionReviewRequest(BaseModel):
    decision: ExtractionReviewDecision
    corrected_order: ExtractedOrder | None = None
    correction_codes: list[ExtractionCorrectionCode] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=500)


class ExtractionAuditDetail(BaseModel):
    audit: dict[str, object]
    review: ExtractionReview | None = None

    @classmethod
    def from_domain(
        cls,
        audit: ExtractionAuditRecord,
        review: ExtractionReview | None,
    ) -> "ExtractionAuditDetail":
        public = audit.model_dump(mode="json", exclude={"source_fingerprint"})
        return cls(audit=public, review=review)


class ExtractionAuditSummary(BaseModel):
    total_extraction_attempts: int
    rollout_mode_counts: dict[str, int]
    processing_outcome_counts: dict[str, int]
    grounding_issue_counts: dict[str, int]
    llm_error_counts: dict[str, int]
    review_decision_counts: dict[str, int]
    review_correction_rate: float
    latency_ms_p50: int | None
    latency_ms_p95: int | None


class LLMRuntimeSummary(BaseModel):
    current_in_flight: int
    current_queue_depth: int
    configured_max_concurrency: int
    configured_queue_capacity: int
    total_accepted: int
    capacity_rejected: int
    queue_timeout_count: int
    provider_failure_count: int
    circuit_open_rejection_count: int
    current_circuit_state: str
    circuit_opened_count: int
    inference_ms_p50: int | None
    inference_ms_p95: int | None
    queue_wait_ms_p50: int | None
    queue_wait_ms_p95: int | None


class SubmissionRequest(BaseModel):
    """Compatibility body; ERP idempotency and correlation are server-owned."""

    model_config = ConfigDict(extra="ignore")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


AUTH_ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Missing or invalid demo identity."},
    403: {"model": ErrorResponse, "description": "Authenticated actor lacks permission."},
}
