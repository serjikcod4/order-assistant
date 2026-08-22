from uuid import UUID

from order_assistant.domain import (
    DraftNotFoundError,
    ExtractionAuditNotFoundError,
    ExtractionAuditRecord,
    ExtractionReview,
    ExtractionReviewConflictError,
    OrderDraft,
    OrderSubmission,
    SubmissionNotFoundError,
)


class InMemoryDraftRepository:
    def __init__(self, store: dict[UUID, OrderDraft] | None = None) -> None:
        self._drafts = store if store is not None else {}

    def save(self, draft: OrderDraft) -> None:
        self._drafts[draft.draft_id] = draft

    def get(self, draft_id: UUID) -> OrderDraft:
        try:
            return self._drafts[draft_id]
        except KeyError as error:
            raise DraftNotFoundError(f"Draft {draft_id} was not found.") from error


class InMemorySubmissionRepository:
    def __init__(self, store: dict[UUID, OrderSubmission] | None = None) -> None:
        self._submissions = store if store is not None else {}

    def save(self, submission: OrderSubmission) -> None:
        self._submissions[submission.submission_id] = submission

    def get(self, submission_id: UUID) -> OrderSubmission:
        try:
            return self._submissions[submission_id]
        except KeyError as error:
            raise SubmissionNotFoundError(
                f"Submission {submission_id} was not found."
            ) from error

    def find_by_draft_id(self, draft_id: UUID) -> OrderSubmission | None:
        return next(
            (
                submission
                for submission in self._submissions.values()
                if submission.draft_id == draft_id
            ),
            None,
        )


class InMemoryExtractionAuditRepository:
    def __init__(
        self,
        store: dict[UUID, ExtractionAuditRecord] | None = None,
    ) -> None:
        self._audits = store if store is not None else {}

    def save(self, audit: ExtractionAuditRecord) -> None:
        self._audits[audit.audit_id] = audit.model_copy(deep=True)

    def get(self, audit_id: UUID) -> ExtractionAuditRecord:
        try:
            return self._audits[audit_id].model_copy(deep=True)
        except KeyError as error:
            raise ExtractionAuditNotFoundError(
                f"Extraction audit {audit_id} was not found."
            ) from error

    def list_all(self) -> list[ExtractionAuditRecord]:
        return [audit.model_copy(deep=True) for audit in self._audits.values()]


class InMemoryExtractionReviewRepository:
    def __init__(
        self,
        store: dict[UUID, ExtractionReview] | None = None,
    ) -> None:
        self._reviews = store if store is not None else {}

    def save(self, review: ExtractionReview) -> None:
        if review.audit_id in self._reviews:
            raise ExtractionReviewConflictError(
                f"Extraction audit {review.audit_id} was already reviewed."
            )
        self._reviews[review.audit_id] = review.model_copy(deep=True)

    def get_by_audit_id(self, audit_id: UUID) -> ExtractionReview | None:
        review = self._reviews.get(audit_id)
        return review.model_copy(deep=True) if review else None

    def list_all(self) -> list[ExtractionReview]:
        return [review.model_copy(deep=True) for review in self._reviews.values()]
