class InvalidDraftResultError(ValueError):
    pass


class DraftNotFoundError(LookupError):
    pass


class InvalidStatusTransitionError(ValueError):
    pass


class ERPTimeoutError(RuntimeError):
    code = "erp_timeout"


class ERPUnavailableError(RuntimeError):
    code = "erp_unavailable"


class ERPAuthenticationError(RuntimeError):
    code = "erp_authentication_failed"


class ERPContractError(RuntimeError):
    code = "erp_contract_error"


class ERPConflictError(RuntimeError):
    code = "erp_idempotency_conflict"


class ERPPermanentError(RuntimeError):
    code = "erp_permanent_failure"


class ERPRateLimitedError(ERPUnavailableError):
    code = "erp_rate_limited"


class SubmissionNotFoundError(LookupError):
    pass


class InvalidSubmissionStateError(ValueError):
    pass


class IdempotencyKeyConflictError(ValueError):
    pass


class PermissionDeniedError(PermissionError):
    pass


class UnauthenticatedError(PermissionError):
    pass


class ExtractorDisabledError(RuntimeError):
    pass


class LLMUnavailableError(RuntimeError):
    pass


class LLMTimeoutError(RuntimeError):
    pass


class LLMBadResponseError(RuntimeError):
    pass


class LLMInvalidOutputError(RuntimeError):
    pass


class LLMHTTPServerError(LLMBadResponseError):
    pass


class LLMMalformedResponseError(LLMBadResponseError):
    pass


class LLMRuntimeRejectedError(RuntimeError):
    code = "llm_runtime_rejected"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = max(1, retry_after)


class LLMCapacityExceededError(LLMRuntimeRejectedError):
    code = "llm_capacity_exceeded"


class LLMQueueTimeoutError(LLMRuntimeRejectedError):
    code = "llm_queue_timeout"


class LLMCircuitOpenError(LLMRuntimeRejectedError):
    code = "llm_circuit_open"


class ExtractionAuditNotFoundError(LookupError):
    pass


class ExtractionReviewConflictError(ValueError):
    pass
