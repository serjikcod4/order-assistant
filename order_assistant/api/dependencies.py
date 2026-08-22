from typing import Annotated

from fastapi import Header, Request

from order_assistant.api.container import AppContainer
from order_assistant.domain import Actor


def get_current_actor(
    request: Request,
    actor_id: Annotated[
        str | None,
        Header(
            alias="X-Demo-Actor-Id",
            description="Required development-only actor ID header.",
        ),
    ] = None,
    actor_role: Annotated[
        str | None,
        Header(
            alias="X-Demo-Actor-Role",
            description="Required development-only actor role header.",
        ),
    ] = None,
) -> Actor:
    """Resolve development-only identity from explicit Swagger-visible headers."""
    container: AppContainer = request.app.state.container
    return container.identity_provider.get_actor(actor_id, actor_role)
