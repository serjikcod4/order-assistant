import hashlib
import hmac
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID, uuid4

from order_assistant.application.clarifications import QUESTION_BY_CODE
from order_assistant.application.drafts import DraftService
from order_assistant.application.ports import (
    ExtractionAuditRepository,
    ExtractionReviewRepository,
    OrderExtractor,
)
from order_assistant.application.runtime import (
    LLMRuntimeController,
    RuntimeCallMetrics,
)
from order_assistant.application.workflow import process_extracted_order
from order_assistant.domain import (
    ExtractedOrder,
    ExtractionAuditRecord,
    ExtractionCorrectionCode,
    ExtractionProcessingOutcome,
    ExtractionReview,
    ExtractionReviewDecision,
    ExtractorDisabledError,
    GroundingIssue,
    LLMBadResponseError,
    LLMHTTPServerError,
    LLMInvalidOutputError,
    LLMMalformedResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMRolloutMode,
    OrderDraft,
    OrderProcessingResult,
    OrderProcessingStatus,
)


@dataclass(frozen=True)
class ExtractionRunResult:
    audit: ExtractionAuditRecord
    extracted: ExtractedOrder
    grounding_issues: list[GroundingIssue]
    processing: OrderProcessingResult | None = None
    draft: OrderDraft | None = None


class ExtractionAuditService:
    """Coordinate staged extraction without retaining customer text."""

    def __init__(
        self,
        *,
        rollout_mode: LLMRolloutMode,
        extractor: OrderExtractor | None,
        inventory: list,
        draft_service: DraftService,
        audit_repository: ExtractionAuditRepository,
        review_repository: ExtractionReviewRepository,
        hmac_key: str,
        extractor_backend: str,
        model_name: str,
        prompt_version: str,
        guard_version: str,
    ) -> None:
        self.rollout_mode = rollout_mode
        self.extractor = extractor
        self.inventory = inventory
        self.draft_service = draft_service
        self.audit_repository = audit_repository
        self.review_repository = review_repository
        self._hmac_key = hmac_key.encode("utf-8")
        self.extractor_backend = extractor_backend
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.guard_version = guard_version

    def fingerprint(self, source_text: str) -> str:
        return hmac.new(
            self._hmac_key,
            source_text.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def process_text(
        self,
        source_text: str,
        request_id: UUID,
    ) -> ExtractionRunResult:
        if self.rollout_mode == LLMRolloutMode.DISABLED or self.extractor is None:
            raise ExtractorDisabledError("Text extraction backend is disabled.")

        started = perf_counter()
        try:
            extracted = self.extractor.extract(source_text)
        except Exception as error:
            latency_ms = round((perf_counter() - started) * 1000)
            runtime_metrics = self._runtime_metrics()
            audit = self._new_audit(
                request_id=request_id,
                source_text=source_text,
                latency_ms=latency_ms,
                outcome=ExtractionProcessingOutcome.LLM_ERROR,
                issues=[],
                draft_id=None,
                llm_error_code=_llm_error_code(error),
                runtime_metrics=runtime_metrics,
            )
            self.audit_repository.save(audit)
            raise

        latency_ms = round((perf_counter() - started) * 1000)
        runtime_metrics = self._runtime_metrics()
        grounding = getattr(self.extractor, "last_grounding_result", None)
        issues = grounding.issues if grounding is not None else []

        if self.rollout_mode == LLMRolloutMode.SHADOW:
            audit = self._new_audit(
                request_id=request_id,
                source_text=source_text,
                latency_ms=latency_ms,
                outcome=ExtractionProcessingOutcome.SHADOW_PROCESSED,
                issues=issues,
                draft_id=None,
                runtime_metrics=runtime_metrics,
            )
            self.audit_repository.save(audit)
            return ExtractionRunResult(audit, extracted, issues)

        processing = process_extracted_order(extracted, self.inventory)
        draft = None
        if processing.status == OrderProcessingStatus.DRAFT_READY:
            draft = self.draft_service.create_draft(processing)
            outcome = ExtractionProcessingOutcome.DRAFT_READY
        elif processing.status == OrderProcessingStatus.NEEDS_CLARIFICATION:
            outcome = ExtractionProcessingOutcome.CLARIFICATION_NEEDED
        else:
            outcome = ExtractionProcessingOutcome.NO_MATCH
        audit = self._new_audit(
            request_id=request_id,
            source_text=source_text,
            latency_ms=latency_ms,
            outcome=outcome,
            issues=issues,
            draft_id=draft.draft_id if draft else None,
            runtime_metrics=runtime_metrics,
        )
        self.audit_repository.save(audit)
        return ExtractionRunResult(audit, extracted, issues, processing, draft)

    def _new_audit(
        self,
        *,
        request_id: UUID,
        source_text: str,
        latency_ms: int,
        outcome: ExtractionProcessingOutcome,
        issues: list[GroundingIssue],
        draft_id: UUID | None,
        llm_error_code: str | None = None,
        runtime_metrics: RuntimeCallMetrics | None = None,
    ) -> ExtractionAuditRecord:
        issue_codes = list(dict.fromkeys(issue.code for issue in issues))
        runtime_metrics = runtime_metrics or RuntimeCallMetrics(
            total_extraction_ms=latency_ms
        )
        return ExtractionAuditRecord(
            audit_id=uuid4(),
            request_id=request_id,
            created_at=datetime.now(timezone.utc),
            rollout_mode=self.rollout_mode,
            extractor_backend=self.extractor_backend,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            guard_version=self.guard_version,
            latency_ms=latency_ms,
            processing_outcome=outcome,
            grounding_issue_codes=issue_codes,
            clarification_codes=[
                code for code in issue_codes if code in QUESTION_BY_CODE
            ],
            source_text_length=len(source_text),
            source_fingerprint=self.fingerprint(source_text),
            draft_id=draft_id,
            llm_error_code=llm_error_code,
            queue_wait_ms=runtime_metrics.queue_wait_ms,
            inference_ms=runtime_metrics.inference_ms,
            total_extraction_ms=latency_ms,
            runtime_attempt_count=runtime_metrics.runtime_attempt_count,
            circuit_state_at_start=runtime_metrics.circuit_state_at_start,
            capacity_rejected=runtime_metrics.capacity_rejected,
            queue_timed_out=runtime_metrics.queue_timed_out,
        )

    def _runtime_metrics(self) -> RuntimeCallMetrics | None:
        controller = _find_runtime_controller(self.extractor)
        return controller.last_call_metrics if controller else None

    def get_audit(
        self, audit_id: UUID
    ) -> tuple[ExtractionAuditRecord, ExtractionReview | None]:
        audit = self.audit_repository.get(audit_id)
        return audit, self.review_repository.get_by_audit_id(audit_id)

    def review(
        self,
        *,
        audit_id: UUID,
        reviewer_actor_id: str,
        decision: ExtractionReviewDecision,
        corrected_order: ExtractedOrder | None,
        correction_codes: list[ExtractionCorrectionCode],
        comment: str | None,
    ) -> ExtractionReview:
        self.audit_repository.get(audit_id)
        review = ExtractionReview(
            audit_id=audit_id,
            reviewer_actor_id=reviewer_actor_id,
            reviewed_at=datetime.now(timezone.utc),
            decision=decision,
            corrected_order=corrected_order,
            correction_codes=list(dict.fromkeys(correction_codes)),
            comment=comment,
        )
        self.review_repository.save(review)
        return review

    def summary(self) -> dict[str, object]:
        audits = self.audit_repository.list_all()
        reviews = self.review_repository.list_all()
        corrected = sum(
            review.decision == ExtractionReviewDecision.CORRECTED
            for review in reviews
        )
        latencies = sorted(audit.latency_ms for audit in audits)
        return {
            "total_extraction_attempts": len(audits),
            "rollout_mode_counts": _counts(a.rollout_mode.value for a in audits),
            "processing_outcome_counts": _counts(
                a.processing_outcome.value for a in audits
            ),
            "grounding_issue_counts": _counts(
                code.value for audit in audits for code in audit.grounding_issue_codes
            ),
            "llm_error_counts": _counts(
                audit.llm_error_code
                for audit in audits
                if audit.llm_error_code is not None
            ),
            "review_decision_counts": _counts(
                review.decision.value for review in reviews
            ),
            "review_correction_rate": corrected / len(reviews) if reviews else 0.0,
            "latency_ms_p50": _percentile(latencies, 0.50),
            "latency_ms_p95": _percentile(latencies, 0.95),
        }

    def runtime_summary(self) -> dict[str, object]:
        audits = self.audit_repository.list_all()
        controller = _find_runtime_controller(self.extractor)
        snapshot = controller.snapshot() if controller else {
            "current_in_flight": 0,
            "current_queue_depth": 0,
            "configured_max_concurrency": 0,
            "configured_queue_capacity": 0,
            "current_circuit_state": "closed",
            "circuit_opened_count": 0,
        }
        provider_error_codes = {
            "llm_unavailable",
            "llm_timeout",
            "llm_http_server_error",
            "llm_malformed_response",
        }
        inference = sorted(
            audit.inference_ms
            for audit in audits
            if audit.runtime_attempt_count > 0
        )
        queue_wait = sorted(audit.queue_wait_ms for audit in audits)
        snapshot.update(
            {
                "total_accepted": sum(
                    audit.runtime_attempt_count > 0 for audit in audits
                ),
                "capacity_rejected": sum(
                    audit.capacity_rejected for audit in audits
                ),
                "queue_timeout_count": sum(
                    audit.queue_timed_out for audit in audits
                ),
                "provider_failure_count": sum(
                    audit.llm_error_code in provider_error_codes
                    for audit in audits
                ),
                "circuit_open_rejection_count": sum(
                    audit.llm_error_code == "llm_circuit_open"
                    for audit in audits
                ),
                "inference_ms_p50": _percentile(inference, 0.50),
                "inference_ms_p95": _percentile(inference, 0.95),
                "queue_wait_ms_p50": _percentile(queue_wait, 0.50),
                "queue_wait_ms_p95": _percentile(queue_wait, 0.95),
            }
        )
        return snapshot


def _counts(values) -> dict[str, int]:
    return dict(Counter(values))


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * fraction) - 1)
    return values[index]


def _find_runtime_controller(extractor) -> LLMRuntimeController | None:
    current = extractor
    while current is not None:
        if isinstance(current, LLMRuntimeController):
            return current
        current = getattr(current, "extractor", None)
    return None


def _llm_error_code(error: Exception) -> str:
    explicit = getattr(error, "code", None)
    if explicit:
        return explicit
    if isinstance(error, LLMHTTPServerError):
        return "llm_http_server_error"
    if isinstance(error, LLMMalformedResponseError):
        return "llm_malformed_response"
    if isinstance(error, LLMTimeoutError):
        return "llm_timeout"
    if isinstance(error, LLMUnavailableError):
        return "llm_unavailable"
    if isinstance(error, LLMInvalidOutputError):
        return "llm_invalid_output"
    if isinstance(error, LLMBadResponseError):
        return "llm_bad_response"
    return type(error).__name__
