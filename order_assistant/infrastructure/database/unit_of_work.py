from sqlalchemy.orm import Session, sessionmaker

from .repositories import (
    SqlAlchemyDraftRepository,
    SqlAlchemyExtractionAuditRepository,
    SqlAlchemyExtractionReviewRepository,
    SqlAlchemySubmissionRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.closed = False

    def __enter__(self):
        if self.closed: raise RuntimeError("Unit of work is closed.")
        self.session = self.session_factory()
        self.drafts = SqlAlchemyDraftRepository(self.session)
        self.submissions = SqlAlchemySubmissionRepository(self.session)
        self.extraction_audits = SqlAlchemyExtractionAuditRepository(self.session)
        self.extraction_reviews = SqlAlchemyExtractionReviewRepository(self.session)
        return self

    def commit(self) -> None: self.session.commit()
    def rollback(self) -> None: self.session.rollback()
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is not None: self.session.rollback()
        self.session.close(); self.closed = True


class SqlAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None: self.session_factory = session_factory
    def __call__(self) -> SqlAlchemyUnitOfWork: return SqlAlchemyUnitOfWork(self.session_factory)
