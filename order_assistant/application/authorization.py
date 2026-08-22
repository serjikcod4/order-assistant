from order_assistant.domain import Actor, ActorRole, Permission, PermissionDeniedError


ROLE_PERMISSIONS: dict[ActorRole, set[Permission]] = {
    ActorRole.VIEWER: {Permission.READ_DRAFT, Permission.READ_SUBMISSION},
    ActorRole.MANAGER: {
        Permission.READ_DRAFT,
        Permission.READ_SUBMISSION,
        Permission.APPROVE_DRAFT,
        Permission.REJECT_DRAFT,
        Permission.REVIEW_EXTRACTION,
    },
    ActorRole.OPERATOR: {
        Permission.READ_DRAFT,
        Permission.READ_SUBMISSION,
        Permission.SUBMIT_ORDER,
        Permission.RETRY_SUBMISSION,
        Permission.RECONCILE_SUBMISSION,
    },
    ActorRole.ADMIN: set(Permission),
}


def require_permission(actor: Actor, permission: Permission) -> None:
    if permission not in ROLE_PERMISSIONS[actor.role]:
        raise PermissionDeniedError(
            f"Actor {actor.actor_id} lacks permission {permission.value}."
        )
