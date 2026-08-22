from copy import deepcopy

from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemoryExtractionAuditRepository,
    InMemoryExtractionReviewRepository,
    InMemorySubmissionRepository,
)


class InMemoryUnitOfWork:
    def __init__(
        self,
        draft_store: dict,
        submission_store: dict,
        audit_store: dict,
        review_store: dict,
    ) -> None:
        self._draft_store = draft_store
        self._submission_store = submission_store
        self._audit_store = audit_store
        self._review_store = review_store
        self._closed = False

    def __enter__(self):
        if self._closed:
            raise RuntimeError("Unit of work is closed.")
        self._working_drafts = deepcopy(self._draft_store)
        self._working_submissions = deepcopy(self._submission_store)
        self._working_audits = deepcopy(self._audit_store)
        self._working_reviews = deepcopy(self._review_store)
        self.drafts = InMemoryDraftRepository(self._working_drafts)
        self.submissions = InMemorySubmissionRepository(self._working_submissions)
        self.extraction_audits = InMemoryExtractionAuditRepository(
            self._working_audits
        )
        self.extraction_reviews = InMemoryExtractionReviewRepository(
            self._working_reviews
        )
        return self

    def commit(self) -> None:
        self._ensure_open()
        self._draft_store.clear(); self._draft_store.update(deepcopy(self._working_drafts))
        self._submission_store.clear(); self._submission_store.update(deepcopy(self._working_submissions))
        self._audit_store.clear(); self._audit_store.update(deepcopy(self._working_audits))
        self._review_store.clear(); self._review_store.update(deepcopy(self._working_reviews))

    def rollback(self) -> None:
        self._ensure_open()
        self._working_drafts = {}; self._working_submissions = {}
        self._working_audits = {}; self._working_reviews = {}

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is not None:
            self.rollback()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Unit of work is closed.")


class InMemoryUnitOfWorkFactory:
    def __init__(
        self,
        drafts: InMemoryDraftRepository,
        submissions: InMemorySubmissionRepository,
        audits: InMemoryExtractionAuditRepository | None = None,
        reviews: InMemoryExtractionReviewRepository | None = None,
    ) -> None:
        self._drafts = drafts._drafts
        self._submissions = submissions._submissions
        self._audits = (audits or InMemoryExtractionAuditRepository())._audits
        self._reviews = (reviews or InMemoryExtractionReviewRepository())._reviews

    def __call__(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(
            self._drafts,
            self._submissions,
            self._audits,
            self._reviews,
        )
