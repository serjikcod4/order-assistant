from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from order_assistant.application.drafts import _RepositoryUow
from order_assistant.application.ports import ERPCallMetadata
from order_assistant.domain import (
    DraftStatus,
    ERPAuthenticationError,
    ERPConflictError,
    ERPContractError,
    ERPPermanentError,
    ERPRateLimitedError,
    ERPTimeoutError,
    ERPUnavailableError,
    IdempotencyKeyConflictError,
    InvalidSubmissionStateError,
    OrderSubmission,
    SubmissionStatus,
)


_UNCERTAIN_CREATE_ERRORS = (
    ERPTimeoutError,
    ERPUnavailableError,
    ERPRateLimitedError,
    ERPContractError,
)
_PERMANENT_CREATE_ERRORS = (
    ERPAuthenticationError,
    ERPConflictError,
    ERPPermanentError,
)
_RECONCILIATION_ERRORS = _UNCERTAIN_CREATE_ERRORS + _PERMANENT_CREATE_ERRORS


def idempotency_key_for_draft(draft_id: UUID) -> str:
    """Generate a stable server-owned key for the public submit endpoint."""
    value = uuid5(NAMESPACE_URL, f"order-assistant:v1:draft:{draft_id}")
    return f"order-assistant-v1-{value}"


class ResilientOrderService:
    """Persist intent, call ERP without a UoW, then persist the outcome."""

    def __init__(self, uow_factory, submissions_or_erp, erp_client=None) -> None:
        if erp_client is None:
            self._uow_factory = uow_factory
            self.erp_client = submissions_or_erp
        else:
            self._uow_factory = lambda: _LegacyBothUow(
                uow_factory,
                submissions_or_erp,
            )
            self.erp_client = erp_client

    def submit_approved_draft(
        self,
        draft_id: UUID,
        idempotency_key: str,
    ) -> OrderSubmission:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty.")

        with self._uow_factory() as uow:
            existing = uow.submissions.find_by_draft_id(draft_id)
            if existing and existing.idempotency_key != idempotency_key:
                raise IdempotencyKeyConflictError(
                    "A different idempotency key is already assigned to this "
                    "draft."
                )
            if existing and existing.status != SubmissionStatus.UNKNOWN:
                return existing

            draft = uow.drafts.get(draft_id)
            if draft.status != DraftStatus.APPROVED:
                raise InvalidSubmissionStateError(
                    "Only approved drafts can be submitted to ERP."
                )
            now = datetime.now(timezone.utc)
            submission = existing or OrderSubmission(
                submission_id=uuid4(),
                draft_id=draft_id,
                idempotency_key=idempotency_key,
                status=SubmissionStatus.PENDING,
                attempt_count=0,
                created_at=now,
                updated_at=now,
                created_order_id=None,
                last_error=None,
                erp_backend=getattr(self.erp_client, "backend", "fake"),
                erp_provider=getattr(
                    self.erp_client,
                    "provider",
                    "in_memory",
                ),
                erp_contract_version=getattr(
                    self.erp_client,
                    "contract_version",
                    "v1",
                ),
            )
            submission.status = SubmissionStatus.PENDING
            submission.attempt_count += 1
            submission.updated_at = now
            uow.submissions.save(submission)
            uow.commit()

        return self._erp_phase(submission, draft)

    def retry_submission(self, submission_id: UUID) -> OrderSubmission:
        with self._uow_factory() as uow:
            submission = uow.submissions.get(submission_id)
            if submission.status not in {
                SubmissionStatus.UNKNOWN,
                SubmissionStatus.PENDING,
            }:
                raise InvalidSubmissionStateError(
                    "Only unknown or pending submissions can be retried."
                )
            draft = uow.drafts.get(submission.draft_id)
            submission.status = SubmissionStatus.PENDING
            submission.attempt_count += 1
            submission.updated_at = datetime.now(timezone.utc)
            uow.submissions.save(submission)
            uow.commit()

        return self._erp_phase(submission, draft)

    def reconcile_submission(self, submission_id: UUID) -> OrderSubmission:
        with self._uow_factory() as uow:
            submission = uow.submissions.get(submission_id)
            draft = uow.drafts.get(submission.draft_id)

        self._set_call_context(submission.correlation_id, draft)
        try:
            order = self.erp_client.get_order_by_idempotency_key(
                submission.idempotency_key
            )
        except _RECONCILIATION_ERRORS as error:
            return self._record_observation(
                submission.submission_id,
                error_message=str(error),
                fallback_error_code=getattr(
                    error,
                    "code",
                    "erp_reconciliation_failed",
                ),
            )
        if order is None:
            return self._record_observation(submission.submission_id)
        return self._success(submission.submission_id, order.order_id)

    def _erp_phase(self, submission: OrderSubmission, draft) -> OrderSubmission:
        self._set_call_context(submission.correlation_id, draft)
        try:
            order = self.erp_client.create_order(
                draft,
                submission.idempotency_key,
            )
        except _UNCERTAIN_CREATE_ERRORS as error:
            return self._failure(
                submission.submission_id,
                SubmissionStatus.UNKNOWN,
                str(error),
                getattr(error, "code", "erp_unknown_outcome"),
            )
        except _PERMANENT_CREATE_ERRORS as error:
            return self._failure(
                submission.submission_id,
                SubmissionStatus.PERMANENTLY_FAILED,
                str(error),
                getattr(error, "code", "erp_permanent_failure"),
            )
        return self._success(submission.submission_id, order.order_id)

    def _success(self, submission_id: UUID, order_id: str) -> OrderSubmission:
        with self._uow_factory() as uow:
            submission = uow.submissions.get(submission_id)
            draft = uow.drafts.get(submission.draft_id)
            submission.status = SubmissionStatus.SUCCEEDED
            submission.created_order_id = order_id
            submission.last_error = None
            submission.normalized_error_code = None
            submission.updated_at = datetime.now(timezone.utc)
            self._apply_metadata(submission)
            draft.status = DraftStatus.ORDER_CREATED
            draft.created_order_id = order_id
            uow.submissions.save(submission)
            uow.drafts.save(draft)
            uow.commit()
            return submission

    def _failure(
        self,
        submission_id: UUID,
        status: SubmissionStatus,
        message: str,
        error_code: str,
    ) -> OrderSubmission:
        with self._uow_factory() as uow:
            submission = uow.submissions.get(submission_id)
            submission.status = status
            submission.last_error = message
            submission.normalized_error_code = error_code
            submission.updated_at = datetime.now(timezone.utc)
            self._apply_metadata(submission)
            uow.submissions.save(submission)
            uow.commit()
            return submission

    def _record_observation(
        self,
        submission_id: UUID,
        error_message: str | None = None,
        fallback_error_code: str | None = None,
    ) -> OrderSubmission:
        with self._uow_factory() as uow:
            submission = uow.submissions.get(submission_id)
            if error_message is not None:
                submission.last_error = error_message
                submission.normalized_error_code = fallback_error_code
            submission.updated_at = datetime.now(timezone.utc)
            self._apply_metadata(submission)
            uow.submissions.save(submission)
            uow.commit()
            return submission

    def _set_call_context(self, correlation_id: UUID, draft) -> None:
        context_setter = getattr(self.erp_client, "set_call_context", None)
        if context_setter is not None:
            context_setter(correlation_id, draft)
            return
        setter = getattr(self.erp_client, "set_correlation_id", None)
        if setter is not None:
            setter(correlation_id)

    def _apply_metadata(self, submission: OrderSubmission) -> None:
        getter = getattr(self.erp_client, "get_last_call_metadata", None)
        if getter is None:
            return
        metadata: ERPCallMetadata | None = getter()
        if metadata is None:
            return
        submission.erp_backend = metadata.backend
        submission.erp_provider = metadata.provider
        submission.erp_contract_version = metadata.contract_version
        submission.correlation_id = metadata.correlation_id
        submission.last_http_status = metadata.http_status
        submission.erp_call_duration_ms = metadata.duration_ms
        if metadata.error_code is not None:
            submission.normalized_error_code = metadata.error_code


class _LegacyBothUow(_RepositoryUow):
    def __init__(self, drafts, submissions) -> None:
        super().__init__(drafts)
        self.submissions = submissions
