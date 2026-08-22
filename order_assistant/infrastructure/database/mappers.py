from datetime import datetime, timezone

from order_assistant.domain import (
    DraftStatus,
    CircuitState,
    ExtractionAuditRecord,
    ExtractionCorrectionCode,
    ExtractionProcessingOutcome,
    ExtractionReview,
    ExtractionReviewDecision,
    GroundingIssueCode,
    LLMRolloutMode,
    OrderDraft,
    OrderProcessingResult,
    OrderSubmission,
    SubmissionStatus,
)

from .models import (
    ExtractionAuditORM,
    ExtractionReviewORM,
    OrderDraftORM,
    OrderSubmissionORM,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def draft_to_orm(draft: OrderDraft, orm: OrderDraftORM | None = None) -> OrderDraftORM:
    orm = orm or OrderDraftORM(draft_id=draft.draft_id)
    orm.status = draft.status.value
    orm.processing_result = draft.processing_result.model_dump(mode="json")
    orm.created_at = draft.created_at
    orm.approved_by = draft.approved_by
    orm.approved_at = draft.approved_at
    orm.rejected_by = draft.rejected_by
    orm.rejected_at = draft.rejected_at
    orm.created_order_id = draft.created_order_id
    return orm


def draft_from_orm(orm: OrderDraftORM) -> OrderDraft:
    return OrderDraft(
        draft_id=orm.draft_id,
        status=DraftStatus(orm.status),
        processing_result=OrderProcessingResult.model_validate(orm.processing_result),
        created_at=_utc(orm.created_at),
        approved_by=orm.approved_by,
        approved_at=_utc(orm.approved_at),
        rejected_by=orm.rejected_by,
        rejected_at=_utc(orm.rejected_at),
        created_order_id=orm.created_order_id,
    )


def submission_to_orm(
    submission: OrderSubmission,
    orm: OrderSubmissionORM | None = None,
) -> OrderSubmissionORM:
    orm = orm or OrderSubmissionORM(submission_id=submission.submission_id)
    orm.draft_id = submission.draft_id
    orm.idempotency_key = submission.idempotency_key
    orm.status = submission.status.value
    orm.attempt_count = submission.attempt_count
    orm.created_at = submission.created_at
    orm.updated_at = submission.updated_at
    orm.created_order_id = submission.created_order_id
    orm.last_error = submission.last_error
    orm.correlation_id = submission.correlation_id
    orm.erp_backend = submission.erp_backend
    orm.erp_provider = submission.erp_provider
    orm.erp_contract_version = submission.erp_contract_version
    orm.last_http_status = submission.last_http_status
    orm.normalized_error_code = submission.normalized_error_code
    orm.erp_call_duration_ms = submission.erp_call_duration_ms
    return orm


def submission_from_orm(orm: OrderSubmissionORM) -> OrderSubmission:
    return OrderSubmission(
        submission_id=orm.submission_id,
        draft_id=orm.draft_id,
        idempotency_key=orm.idempotency_key,
        status=SubmissionStatus(orm.status),
        attempt_count=orm.attempt_count,
        created_at=_utc(orm.created_at),
        updated_at=_utc(orm.updated_at),
        created_order_id=orm.created_order_id,
        last_error=orm.last_error,
        correlation_id=orm.correlation_id,
        erp_backend=orm.erp_backend,
        erp_provider=orm.erp_provider,
        erp_contract_version=orm.erp_contract_version,
        last_http_status=orm.last_http_status,
        normalized_error_code=orm.normalized_error_code,
        erp_call_duration_ms=orm.erp_call_duration_ms,
    )


def audit_to_orm(
    audit: ExtractionAuditRecord,
    orm: ExtractionAuditORM | None = None,
) -> ExtractionAuditORM:
    orm = orm or ExtractionAuditORM(audit_id=audit.audit_id)
    orm.request_id = audit.request_id
    orm.created_at = audit.created_at
    orm.rollout_mode = audit.rollout_mode.value
    orm.extractor_backend = audit.extractor_backend
    orm.model_name = audit.model_name
    orm.prompt_version = audit.prompt_version
    orm.guard_version = audit.guard_version
    orm.latency_ms = audit.latency_ms
    orm.processing_outcome = audit.processing_outcome.value
    orm.grounding_issue_codes = [code.value for code in audit.grounding_issue_codes]
    orm.clarification_codes = [code.value for code in audit.clarification_codes]
    orm.source_text_length = audit.source_text_length
    orm.source_fingerprint = audit.source_fingerprint
    orm.draft_id = audit.draft_id
    orm.llm_error_code = audit.llm_error_code
    orm.queue_wait_ms = audit.queue_wait_ms
    orm.inference_ms = audit.inference_ms
    orm.total_extraction_ms = audit.total_extraction_ms
    orm.runtime_attempt_count = audit.runtime_attempt_count
    orm.circuit_state_at_start = audit.circuit_state_at_start.value
    orm.capacity_rejected = audit.capacity_rejected
    orm.queue_timed_out = audit.queue_timed_out
    return orm


def audit_from_orm(orm: ExtractionAuditORM) -> ExtractionAuditRecord:
    return ExtractionAuditRecord(
        audit_id=orm.audit_id,
        request_id=orm.request_id,
        created_at=_utc(orm.created_at),
        rollout_mode=LLMRolloutMode(orm.rollout_mode),
        extractor_backend=orm.extractor_backend,
        model_name=orm.model_name,
        prompt_version=orm.prompt_version,
        guard_version=orm.guard_version,
        latency_ms=orm.latency_ms,
        processing_outcome=ExtractionProcessingOutcome(orm.processing_outcome),
        grounding_issue_codes=[GroundingIssueCode(code) for code in orm.grounding_issue_codes],
        clarification_codes=[GroundingIssueCode(code) for code in orm.clarification_codes],
        source_text_length=orm.source_text_length,
        source_fingerprint=orm.source_fingerprint,
        draft_id=orm.draft_id,
        llm_error_code=orm.llm_error_code,
        queue_wait_ms=orm.queue_wait_ms,
        inference_ms=orm.inference_ms,
        total_extraction_ms=orm.total_extraction_ms,
        runtime_attempt_count=orm.runtime_attempt_count,
        circuit_state_at_start=CircuitState(orm.circuit_state_at_start),
        capacity_rejected=orm.capacity_rejected,
        queue_timed_out=orm.queue_timed_out,
    )


def review_to_orm(
    review: ExtractionReview,
    orm: ExtractionReviewORM | None = None,
) -> ExtractionReviewORM:
    orm = orm or ExtractionReviewORM(audit_id=review.audit_id)
    orm.reviewer_actor_id = review.reviewer_actor_id
    orm.reviewed_at = review.reviewed_at
    orm.decision = review.decision.value
    orm.corrected_order = (
        review.corrected_order.model_dump(mode="json")
        if review.corrected_order
        else None
    )
    orm.correction_codes = [code.value for code in review.correction_codes]
    orm.comment = review.comment
    return orm


def review_from_orm(orm: ExtractionReviewORM) -> ExtractionReview:
    return ExtractionReview(
        audit_id=orm.audit_id,
        reviewer_actor_id=orm.reviewer_actor_id,
        reviewed_at=_utc(orm.reviewed_at),
        decision=ExtractionReviewDecision(orm.decision),
        corrected_order=orm.corrected_order,
        correction_codes=[
            ExtractionCorrectionCode(code) for code in orm.correction_codes
        ],
        comment=orm.comment,
    )
