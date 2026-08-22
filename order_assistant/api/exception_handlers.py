from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from order_assistant.domain import (
    DraftNotFoundError,
    ERPPermanentError,
    IdempotencyKeyConflictError,
    InvalidDraftResultError,
    InvalidStatusTransitionError,
    InvalidSubmissionStateError,
    PermissionDeniedError,
    SubmissionNotFoundError,
    UnauthenticatedError,
    ExtractorDisabledError,
    LLMBadResponseError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMRuntimeRejectedError,
    ExtractionAuditNotFoundError,
    ExtractionReviewConflictError,
)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMRuntimeRejectedError)
    async def handle_runtime_rejection(
        request: Request,
        error: LLMRuntimeRejectedError,
    ) -> JSONResponse:
        response = _error_response(503, error.code, str(error))
        response.headers["Retry-After"] = str(error.retry_after)
        return response

    @app.exception_handler(ExtractorDisabledError)
    async def handle_disabled_extractor(request: Request, error: ExtractorDisabledError) -> JSONResponse:
        return _error_response(503, "extractor_disabled", str(error))

    @app.exception_handler(LLMUnavailableError)
    async def handle_llm_unavailable(request: Request, error: LLMUnavailableError) -> JSONResponse:
        return _error_response(503, "llm_unavailable", str(error))

    @app.exception_handler(LLMTimeoutError)
    async def handle_llm_timeout(request: Request, error: LLMTimeoutError) -> JSONResponse:
        return _error_response(504, "llm_timeout", str(error))

    @app.exception_handler(LLMBadResponseError)
    async def handle_llm_bad_response(request: Request, error: LLMBadResponseError) -> JSONResponse:
        return _error_response(502, "llm_bad_response", str(error))

    @app.exception_handler(LLMInvalidOutputError)
    async def handle_llm_invalid_output(request: Request, error: LLMInvalidOutputError) -> JSONResponse:
        return _error_response(502, "llm_invalid_output", str(error))

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(422, "validation_error", "Request validation failed.")

    @app.exception_handler(UnauthenticatedError)
    async def handle_unauthenticated(
        request: Request,
        error: UnauthenticatedError,
    ) -> JSONResponse:
        return _error_response(401, "unauthenticated", str(error))

    @app.exception_handler(PermissionDeniedError)
    async def handle_permission_denied(
        request: Request,
        error: PermissionDeniedError,
    ) -> JSONResponse:
        return _error_response(403, "permission_denied", str(error))

    @app.exception_handler(DraftNotFoundError)
    async def handle_missing_draft(
        request: Request,
        error: DraftNotFoundError,
    ) -> JSONResponse:
        return _error_response(404, "draft_not_found", str(error))

    @app.exception_handler(SubmissionNotFoundError)
    async def handle_missing_submission(
        request: Request,
        error: SubmissionNotFoundError,
    ) -> JSONResponse:
        return _error_response(404, "submission_not_found", str(error))

    @app.exception_handler(ExtractionAuditNotFoundError)
    async def handle_missing_extraction_audit(
        request: Request,
        error: ExtractionAuditNotFoundError,
    ) -> JSONResponse:
        return _error_response(404, "extraction_audit_not_found", str(error))

    @app.exception_handler(ExtractionReviewConflictError)
    async def handle_review_conflict(
        request: Request,
        error: ExtractionReviewConflictError,
    ) -> JSONResponse:
        return _error_response(409, "extraction_review_conflict", str(error))

    @app.exception_handler(IdempotencyKeyConflictError)
    async def handle_key_conflict(
        request: Request,
        error: IdempotencyKeyConflictError,
    ) -> JSONResponse:
        return _error_response(409, "idempotency_key_conflict", str(error))

    @app.exception_handler(InvalidStatusTransitionError)
    @app.exception_handler(InvalidSubmissionStateError)
    @app.exception_handler(InvalidDraftResultError)
    async def handle_invalid_state(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        return _error_response(409, "invalid_status_transition", str(error))

    @app.exception_handler(ERPPermanentError)
    async def handle_erp_failure(
        request: Request,
        error: ERPPermanentError,
    ) -> JSONResponse:
        return _error_response(502, "erp_permanent_failure", str(error))

    @app.exception_handler(ValueError)
    async def handle_invalid_value(
        request: Request,
        error: ValueError,
    ) -> JSONResponse:
        return _error_response(422, "invalid_request", str(error))
