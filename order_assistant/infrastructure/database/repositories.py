from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from order_assistant.domain import (
    DraftNotFoundError,
    ExtractionAuditNotFoundError,
    ExtractionAuditRecord,
    ExtractionReview,
    ExtractionReviewConflictError,
    IdempotencyKeyConflictError,
    OrderDraft,
    OrderSubmission,
    SubmissionNotFoundError,
)

from .mappers import (
    audit_from_orm,
    audit_to_orm,
    draft_from_orm,
    draft_to_orm,
    review_from_orm,
    review_to_orm,
    submission_from_orm,
    submission_to_orm,
)
from .models import (
    ExtractionAuditORM,
    ExtractionReviewORM,
    OrderDraftORM,
    OrderSubmissionORM,
)


class SqlAlchemyDraftRepository:
    def __init__(self, session_factory: sessionmaker[Session] | Session) -> None:
        self.session_factory = session_factory

    def save(self, draft: OrderDraft) -> None:
        if isinstance(self.session_factory, Session):
            session = self.session_factory
            orm = session.get(OrderDraftORM, draft.draft_id)
            session.add(draft_to_orm(draft, orm)); session.flush(); return
        with self.session_factory() as session:
            orm = session.get(OrderDraftORM, draft.draft_id)
            session.add(draft_to_orm(draft, orm))
            session.commit()

    def get(self, draft_id: UUID) -> OrderDraft:
        if isinstance(self.session_factory, Session):
            orm = self.session_factory.get(OrderDraftORM, draft_id)
            if orm is None: raise DraftNotFoundError(f"Draft {draft_id} was not found.")
            return draft_from_orm(orm)
        with self.session_factory() as session:
            orm = session.get(OrderDraftORM, draft_id)
            if orm is None:
                raise DraftNotFoundError(f"Draft {draft_id} was not found.")
            return draft_from_orm(orm)


class SqlAlchemySubmissionRepository:
    def __init__(self, session_factory: sessionmaker[Session] | Session) -> None:
        self.session_factory = session_factory

    def save(self, submission: OrderSubmission) -> None:
        try:
            if isinstance(self.session_factory, Session):
                orm = self.session_factory.get(OrderSubmissionORM, submission.submission_id)
                self.session_factory.add(submission_to_orm(submission, orm)); self.session_factory.flush(); return
            with self.session_factory() as session:
                orm = session.get(OrderSubmissionORM, submission.submission_id)
                session.add(submission_to_orm(submission, orm))
                session.commit()
        except IntegrityError as error:
            raise IdempotencyKeyConflictError(
                "Submission idempotency key or draft is already in use."
            ) from error

    def get(self, submission_id: UUID) -> OrderSubmission:
        if isinstance(self.session_factory, Session):
            orm = self.session_factory.get(OrderSubmissionORM, submission_id)
            if orm is None: raise SubmissionNotFoundError(f"Submission {submission_id} was not found.")
            return submission_from_orm(orm)
        with self.session_factory() as session:
            orm = session.get(OrderSubmissionORM, submission_id)
            if orm is None:
                raise SubmissionNotFoundError(
                    f"Submission {submission_id} was not found."
                )
            return submission_from_orm(orm)

    def find_by_draft_id(self, draft_id: UUID) -> OrderSubmission | None:
        if isinstance(self.session_factory, Session):
            orm = self.session_factory.scalar(select(OrderSubmissionORM).where(OrderSubmissionORM.draft_id == draft_id))
            return submission_from_orm(orm) if orm is not None else None
        with self.session_factory() as session:
            orm = session.scalar(
                select(OrderSubmissionORM).where(
                    OrderSubmissionORM.draft_id == draft_id
                )
            )
            return submission_from_orm(orm) if orm is not None else None


class SqlAlchemyExtractionAuditRepository:
    def __init__(self, session_factory: sessionmaker[Session] | Session) -> None:
        self.session_factory = session_factory

    def save(self, audit: ExtractionAuditRecord) -> None:
        if isinstance(self.session_factory, Session):
            orm = self.session_factory.get(ExtractionAuditORM, audit.audit_id)
            self.session_factory.add(audit_to_orm(audit, orm))
            self.session_factory.flush()
            return
        with self.session_factory() as session:
            orm = session.get(ExtractionAuditORM, audit.audit_id)
            session.add(audit_to_orm(audit, orm))
            session.commit()

    def get(self, audit_id: UUID) -> ExtractionAuditRecord:
        if isinstance(self.session_factory, Session):
            orm = self.session_factory.get(ExtractionAuditORM, audit_id)
            if orm is None:
                raise ExtractionAuditNotFoundError(
                    f"Extraction audit {audit_id} was not found."
                )
            return audit_from_orm(orm)
        with self.session_factory() as session:
            orm = session.get(ExtractionAuditORM, audit_id)
            if orm is None:
                raise ExtractionAuditNotFoundError(
                    f"Extraction audit {audit_id} was not found."
                )
            return audit_from_orm(orm)

    def list_all(self) -> list[ExtractionAuditRecord]:
        if isinstance(self.session_factory, Session):
            rows = self.session_factory.scalars(
                select(ExtractionAuditORM).order_by(ExtractionAuditORM.created_at)
            )
            return [audit_from_orm(row) for row in rows]
        with self.session_factory() as session:
            rows = session.scalars(
                select(ExtractionAuditORM).order_by(ExtractionAuditORM.created_at)
            )
            return [audit_from_orm(row) for row in rows]


class SqlAlchemyExtractionReviewRepository:
    def __init__(self, session_factory: sessionmaker[Session] | Session) -> None:
        self.session_factory = session_factory

    def save(self, review: ExtractionReview) -> None:
        try:
            if isinstance(self.session_factory, Session):
                if self.session_factory.get(ExtractionReviewORM, review.audit_id):
                    raise ExtractionReviewConflictError(
                        f"Extraction audit {review.audit_id} was already reviewed."
                    )
                self.session_factory.add(review_to_orm(review))
                self.session_factory.flush()
                return
            with self.session_factory() as session:
                if session.get(ExtractionReviewORM, review.audit_id):
                    raise ExtractionReviewConflictError(
                        f"Extraction audit {review.audit_id} was already reviewed."
                    )
                session.add(review_to_orm(review))
                session.commit()
        except IntegrityError as error:
            raise ExtractionReviewConflictError(
                f"Extraction audit {review.audit_id} was already reviewed."
            ) from error

    def get_by_audit_id(self, audit_id: UUID) -> ExtractionReview | None:
        if isinstance(self.session_factory, Session):
            orm = self.session_factory.get(ExtractionReviewORM, audit_id)
            return review_from_orm(orm) if orm else None
        with self.session_factory() as session:
            orm = session.get(ExtractionReviewORM, audit_id)
            return review_from_orm(orm) if orm else None

    def list_all(self) -> list[ExtractionReview]:
        if isinstance(self.session_factory, Session):
            rows = self.session_factory.scalars(
                select(ExtractionReviewORM).order_by(ExtractionReviewORM.reviewed_at)
            )
            return [review_from_orm(row) for row in rows]
        with self.session_factory() as session:
            rows = session.scalars(
                select(ExtractionReviewORM).order_by(ExtractionReviewORM.reviewed_at)
            )
            return [review_from_orm(row) for row in rows]
