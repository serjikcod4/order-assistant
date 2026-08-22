from contextlib import asynccontextmanager

from fastapi import FastAPI

from order_assistant.api.container import AppContainer, create_container
from order_assistant.api.exception_handlers import register_exception_handlers
from order_assistant.api.routers import (
    drafts,
    extraction_audits,
    health,
    order_requests,
    runtime,
    submissions,
)


def create_app(container: AppContainer | None = None) -> FastAPI:
    """Create an API application with explicit, injectable in-memory state."""
    app_container = container or create_container()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        application.state.container.dispose()

    application = FastAPI(
        title="B2B Order Assistant",
        version="0.1.0",
        description=(
            "Order workflow API with deterministic business rules, staged "
            "local extraction and replaceable persistence adapters."
        ),
        lifespan=lifespan,
    )
    application.state.container = app_container

    @application.middleware("http")
    async def add_request_id_header(request, call_next):
        response = await call_next(request)
        request_id = getattr(request.state, "request_id", None)
        if request_id is not None:
            response.headers["X-Request-ID"] = str(request_id)
        return response

    register_exception_handlers(application)
    application.include_router(health.router)
    application.include_router(order_requests.router, prefix="/api/v1")
    application.include_router(extraction_audits.router, prefix="/api/v1")
    application.include_router(runtime.router, prefix="/api/v1")
    application.include_router(drafts.router, prefix="/api/v1")
    application.include_router(submissions.router, prefix="/api/v1")
    return application


app = create_app()
