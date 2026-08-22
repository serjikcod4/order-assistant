from dataclasses import dataclass

from sqlalchemy import Engine

from order_assistant.application.drafts import DraftService
from order_assistant.application.audits import ExtractionAuditService
from order_assistant.application.grounding import (
    ExtractionGroundingGuard,
    GROUNDING_GUARD_VERSION,
    GroundedOrderExtractor,
)
from order_assistant.application.ports import (
    ExtractionAuditRepository,
    ExtractionReviewRepository,
    ERPClient,
    IdentityProvider,
    OrderExtractor,
)
from order_assistant.config import Settings
from order_assistant.application.submissions import ResilientOrderService
from order_assistant.application.runtime import LLMRuntimeController
from order_assistant.domain import InventoryItem, LLMRolloutMode
from order_assistant.infrastructure.demo_data import demo_inventory
from order_assistant.infrastructure.erp import ResilientFakeERPClient
from order_assistant.infrastructure.http_erp import HTTPERPClient
from order_assistant.infrastructure.identity import DemoHeaderIdentityProvider
from order_assistant.infrastructure.health import (
    ReadinessService,
    database_probe,
    ollama_health_probe,
)
from order_assistant.infrastructure.extractors import OllamaOrderExtractor
from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemoryExtractionAuditRepository,
    InMemoryExtractionReviewRepository,
    InMemorySubmissionRepository,
)
from order_assistant.infrastructure.database.repositories import (
    SqlAlchemyDraftRepository,
    SqlAlchemyExtractionAuditRepository,
    SqlAlchemyExtractionReviewRepository,
    SqlAlchemySubmissionRepository,
)
from order_assistant.infrastructure.database.session import create_engine_and_session_factory
from order_assistant.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWorkFactory
from order_assistant.infrastructure.unit_of_work import InMemoryUnitOfWorkFactory


@dataclass
class AppContainer:
    inventory: list[InventoryItem]
    draft_repository: object
    submission_repository: object
    extraction_audit_repository: ExtractionAuditRepository
    extraction_review_repository: ExtractionReviewRepository
    erp_client: ERPClient
    draft_service: DraftService
    submission_service: ResilientOrderService
    identity_provider: IdentityProvider
    order_extractor: OrderExtractor | None
    extraction_audit_service: ExtractionAuditService
    rollout_mode: LLMRolloutMode
    runtime_controller: LLMRuntimeController | None = None
    readiness_service: ReadinessService | None = None
    settings: Settings | None = None
    engine: Engine | None = None
    uow_factory: object | None = None

    def dispose(self) -> None:
        close = getattr(self.order_extractor, "close", None)
        if close is not None:
            close()
        erp_close = getattr(self.erp_client, "close", None)
        if erp_close is not None:
            erp_close()
        if self.engine is not None:
            self.engine.dispose()
        if self.readiness_service is not None:
            self.readiness_service.close()


def create_container(
    identity_provider: IdentityProvider | None = None,
    settings: Settings | None = None,
    order_extractor: OrderExtractor | None = None,
) -> AppContainer:
    """Create the demo configuration; all data is process-local memory."""
    settings_were_explicit = settings is not None
    settings = settings or Settings()
    rollout_mode = LLMRolloutMode(settings.llm_rollout_mode)
    runtime_controller = None
    if order_extractor is not None and not settings_were_explicit:
        # Explicit dependency injection keeps legacy offline API tests useful.
        rollout_mode = LLMRolloutMode.REVIEW
    elif (
        order_extractor is not None
        and rollout_mode != LLMRolloutMode.DISABLED
        and not isinstance(order_extractor, GroundedOrderExtractor)
    ):
        if isinstance(order_extractor, OllamaOrderExtractor):
            runtime_controller = _runtime_controller(order_extractor, settings)
            order_extractor = runtime_controller
        order_extractor = GroundedOrderExtractor(
            order_extractor,
            ExtractionGroundingGuard(),
        )
    if settings.persistence_backend == "sqlalchemy" and not settings.database_url:
        raise ValueError("database_url is required for sqlalchemy persistence.")

    engine = None
    if settings.persistence_backend == "sqlalchemy":
        engine, session_factory = create_engine_and_session_factory(settings.database_url)
        draft_repository = SqlAlchemyDraftRepository(session_factory)
        submission_repository = SqlAlchemySubmissionRepository(session_factory)
        audit_repository = SqlAlchemyExtractionAuditRepository(session_factory)
        review_repository = SqlAlchemyExtractionReviewRepository(session_factory)
        uow_factory = SqlAlchemyUnitOfWorkFactory(session_factory)
    else:
        draft_repository = InMemoryDraftRepository()
        submission_repository = InMemorySubmissionRepository()
        audit_repository = InMemoryExtractionAuditRepository()
        review_repository = InMemoryExtractionReviewRepository()
        uow_factory = InMemoryUnitOfWorkFactory(
            draft_repository,
            submission_repository,
            audit_repository,
            review_repository,
        )
    if settings.erp_backend == "http":
        erp_client = HTTPERPClient(
            settings.erp_base_url,
            settings.erp_token.get_secret_value(),
            contract_version=settings.erp_contract_version,
            connect_timeout_seconds=settings.erp_connect_timeout_seconds,
            read_timeout_seconds=settings.erp_read_timeout_seconds,
            write_timeout_seconds=settings.erp_write_timeout_seconds,
            pool_timeout_seconds=settings.erp_pool_timeout_seconds,
            allow_insecure_http=settings.erp_allow_insecure_http,
        )
    else:
        erp_client = ResilientFakeERPClient()
    if (
        order_extractor is None
        and settings.extractor_backend == "ollama"
    ):
        ollama_extractor = OllamaOrderExtractor(
            settings.ollama_base_url,
            settings.ollama_model,
            settings.ollama_timeout_seconds,
            prompt_version=settings.ollama_prompt_version,
            think=settings.ollama_think,
        )
        runtime_controller = _runtime_controller(ollama_extractor, settings)
        order_extractor = GroundedOrderExtractor(
            runtime_controller,
            ExtractionGroundingGuard(),
        )
    draft_service = DraftService(uow_factory, erp_client)
    extractor_backend = (
        settings.extractor_backend
        if settings.extractor_backend != "disabled"
        else (type(order_extractor).__name__ if order_extractor else "disabled")
    )
    audit_service = ExtractionAuditService(
        rollout_mode=rollout_mode,
        extractor=order_extractor,
        inventory=list(demo_inventory),
        draft_service=draft_service,
        audit_repository=audit_repository,
        review_repository=review_repository,
        hmac_key=settings.audit_hmac_key.get_secret_value(),
        extractor_backend=extractor_backend,
        model_name=(settings.ollama_model if extractor_backend == "ollama" else "mock"),
        prompt_version=(
            settings.ollama_prompt_version if extractor_backend == "ollama" else "mock"
        ),
        guard_version=GROUNDING_GUARD_VERSION,
    )
    db_probe = database_probe(engine) if engine is not None else None
    ollama_probe = None
    readiness_close = None
    if settings.extractor_backend == "ollama":
        ollama_probe, readiness_close = ollama_health_probe(
            settings.ollama_base_url,
            settings.ollama_timeout_seconds,
        )
    readiness_service = ReadinessService(
        rollout_mode=rollout_mode,
        extractor_backend=settings.extractor_backend,
        cache_seconds=settings.readiness_cache_seconds,
        database_probe=db_probe,
        ollama_probe=ollama_probe,
        circuit_state=(
            (lambda: runtime_controller.circuit_state)
            if runtime_controller is not None
            else None
        ),
        close_callback=readiness_close,
    )
    return AppContainer(
        inventory=list(demo_inventory),
        draft_repository=draft_repository,
        submission_repository=submission_repository,
        extraction_audit_repository=audit_repository,
        extraction_review_repository=review_repository,
        erp_client=erp_client,
        draft_service=draft_service,
        submission_service=ResilientOrderService(uow_factory, erp_client),
        identity_provider=identity_provider or DemoHeaderIdentityProvider(),
        order_extractor=order_extractor,
        extraction_audit_service=audit_service,
        rollout_mode=rollout_mode,
        runtime_controller=runtime_controller,
        readiness_service=readiness_service,
        settings=settings,
        engine=engine,
        uow_factory=uow_factory,
    )


def _runtime_controller(
    extractor: OllamaOrderExtractor,
    settings: Settings,
) -> LLMRuntimeController:
    return LLMRuntimeController(
        extractor,
        max_concurrency=settings.llm_max_concurrency,
        queue_capacity=settings.llm_queue_capacity,
        queue_wait_timeout_seconds=settings.llm_queue_wait_timeout_seconds,
        failure_threshold=settings.llm_circuit_failure_threshold,
        circuit_open_seconds=settings.llm_circuit_open_seconds,
        half_open_max_calls=settings.llm_circuit_half_open_max_calls,
        transport_max_attempts=settings.llm_transport_max_attempts,
    )
