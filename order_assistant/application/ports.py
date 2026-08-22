from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from order_assistant.domain import (
    Actor,
    CreatedOrder,
    ExtractionAuditRecord,
    ExtractionReview,
    ExtractedOrder,
    OrderDraft,
    OrderSubmission,
)


class IdentityProvider(Protocol):
    """Resolve an actor from transport-provided identity values."""

    def get_actor(self, actor_id: str | None, actor_role: str | None) -> Actor:
        ...


class OrderExtractor(Protocol):
    def extract(self, customer_message: str) -> ExtractedOrder:
        ...


class DraftRepository(Protocol):
    def save(self, draft: OrderDraft) -> None:
        ...

    def get(self, draft_id: UUID) -> OrderDraft:
        ...


class SubmissionRepository(Protocol):
    def save(self, submission: OrderSubmission) -> None:
        ...

    def get(self, submission_id: UUID) -> OrderSubmission:
        ...

    def find_by_draft_id(self, draft_id: UUID) -> OrderSubmission | None:
        ...


class ExtractionAuditRepository(Protocol):
    def save(self, audit: ExtractionAuditRecord) -> None:
        ...

    def get(self, audit_id: UUID) -> ExtractionAuditRecord:
        ...

    def list_all(self) -> list[ExtractionAuditRecord]:
        ...


class ExtractionReviewRepository(Protocol):
    def save(self, review: ExtractionReview) -> None:
        ...

    def get_by_audit_id(self, audit_id: UUID) -> ExtractionReview | None:
        ...

    def list_all(self) -> list[ExtractionReview]:
        ...


class ERPClient(Protocol):
    def create_order(
        self,
        draft: OrderDraft,
        idempotency_key: str,
    ) -> CreatedOrder:
        ...

    def get_order_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CreatedOrder | None:
        ...


@dataclass(frozen=True)
class ERPCallMetadata:
    backend: str
    provider: str
    contract_version: str
    correlation_id: UUID
    http_status: int | None = None
    error_code: str | None = None
    duration_ms: int | None = None


class UnitOfWork(Protocol):
    drafts: DraftRepository
    submissions: SubmissionRepository
    extraction_audits: ExtractionAuditRepository
    extraction_reviews: ExtractionReviewRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class DraftERPClient(ERPClient, Protocol):
    def get_order(self, order_id: str) -> CreatedOrder:
        ...
