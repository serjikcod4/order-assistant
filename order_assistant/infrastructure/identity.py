from order_assistant.domain import Actor, ActorRole, UnauthenticatedError


class DemoHeaderIdentityProvider:
    """Development-only identity adapter; client-controlled headers are untrusted."""

    def get_actor(self, actor_id: str | None, actor_role: str | None) -> Actor:
        if not actor_id or not actor_role:
            raise UnauthenticatedError("Demo identity headers are required.")
        try:
            role = ActorRole(actor_role)
        except ValueError as error:
            raise UnauthenticatedError("Demo actor role is unknown.") from error
        return Actor(actor_id=actor_id, role=role)
