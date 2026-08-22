import subprocess
import sys

from fastapi.testclient import TestClient

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.domain import Actor, ActorRole, ERPFailureMode


FULL_REQUEST = {
    "model": "6204",
    "quantity": 500,
    "primary_brand": "SKF",
    "fallback_brands": ["FAG"],
    "max_unit_price": "250",
    "delivery_deadline": "2026-08-15T09:00:00",
    "allow_split_fulfillment": False,
    "requires_clarification": False,
    "clarification_questions": [],
}


def headers(actor_id: str, role: str) -> dict[str, str]:
    return {
        "X-Demo-Actor-Id": actor_id,
        "X-Demo-Actor-Role": role,
    }


VIEWER = headers("viewer@example.com", "viewer")
MANAGER = headers("manager@example.com", "manager")
OPERATOR = headers("operator@example.com", "operator")
ADMIN = headers("admin@example.com", "admin")


def client() -> TestClient:
    return TestClient(create_app(create_container()))


def draft_id(test_client: TestClient) -> str:
    response = test_client.post("/api/v1/order-requests", json=FULL_REQUEST)
    assert response.status_code == 201
    return response.json()["draft_id"]


def approved_draft_id(test_client: TestClient) -> str:
    value = draft_id(test_client)
    approved = test_client.post(f"/api/v1/drafts/{value}/approve", headers=MANAGER)
    assert approved.status_code == 200
    return value


def test_missing_or_unknown_identity_returns_401() -> None:
    test_client = client()
    value = draft_id(test_client)

    missing = test_client.get(f"/api/v1/drafts/{value}")
    unknown = test_client.get(
        f"/api/v1/drafts/{value}",
        headers=headers("user@example.com", "unknown"),
    )

    assert missing.status_code == 401
    assert unknown.status_code == 401
    assert missing.json()["error"]["code"] == "unauthenticated"


def test_viewer_can_read_but_cannot_approve_or_submit() -> None:
    test_client = client()
    value = draft_id(test_client)

    read = test_client.get(f"/api/v1/drafts/{value}", headers=VIEWER)
    approve = test_client.post(f"/api/v1/drafts/{value}/approve", headers=VIEWER)
    submit = test_client.post(
        f"/api/v1/drafts/{value}/submit",
        json={"idempotency_key": "viewer-submit"},
        headers=VIEWER,
    )

    assert read.status_code == 200
    assert approve.status_code == 403
    assert submit.status_code == 403


def test_manager_approval_uses_actor_and_ignores_forged_body_identity() -> None:
    test_client = client()
    value = draft_id(test_client)

    approved = test_client.post(
        f"/api/v1/drafts/{value}/approve",
        headers=MANAGER,
        json={"approved_by": "intruder@example.com"},
    )
    submit = test_client.post(
        f"/api/v1/drafts/{value}/submit",
        json={"idempotency_key": "manager-submit"},
        headers=MANAGER,
    )

    assert approved.status_code == 200
    assert approved.json()["approved_by"] == "manager@example.com"
    assert submit.status_code == 403


def test_rejection_uses_actor_identity() -> None:
    test_client = client()
    value = draft_id(test_client)

    rejected = test_client.post(
        f"/api/v1/drafts/{value}/reject",
        headers=MANAGER,
        json={"rejected_by": "intruder@example.com"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["rejected_by"] == "manager@example.com"


def test_operator_can_submit_but_cannot_approve() -> None:
    test_client = client()
    value = draft_id(test_client)
    denied_approval = test_client.post(
        f"/api/v1/drafts/{value}/approve",
        headers=OPERATOR,
    )
    test_client.post(f"/api/v1/drafts/{value}/approve", headers=MANAGER)
    submitted = test_client.post(
        f"/api/v1/drafts/{value}/submit",
        json={"idempotency_key": "operator-submit"},
        headers=OPERATOR,
    )

    assert denied_approval.status_code == 403
    assert submitted.status_code == 201


def test_retry_and_reconcile_require_operator_permissions() -> None:
    test_client = client()
    test_client.app.state.container.erp_client.failure_mode = (
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )
    value = approved_draft_id(test_client)
    submitted = test_client.post(
        f"/api/v1/drafts/{value}/submit",
        json={"idempotency_key": "timeout-order"},
        headers=OPERATOR,
    )
    submission_id = submitted.json()["submission_id"]

    viewer_retry = test_client.post(
        f"/api/v1/submissions/{submission_id}/retry",
        headers=VIEWER,
    )
    viewer_reconcile = test_client.post(
        f"/api/v1/submissions/{submission_id}/reconcile",
        headers=VIEWER,
    )
    reconciled = test_client.post(
        f"/api/v1/submissions/{submission_id}/reconcile",
        headers=OPERATOR,
    )

    assert submitted.status_code == 202
    assert viewer_retry.status_code == 403
    assert viewer_reconcile.status_code == 403
    assert reconciled.status_code == 200


def test_admin_can_read_approve_reject_submit_retry_and_reconcile() -> None:
    test_client = client()
    test_client.app.state.container.erp_client.failure_mode = (
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )
    first_draft = draft_id(test_client)
    assert test_client.get(f"/api/v1/drafts/{first_draft}", headers=ADMIN).status_code == 200
    assert test_client.post(
        f"/api/v1/drafts/{first_draft}/approve", headers=ADMIN
    ).status_code == 200
    submitted = test_client.post(
        f"/api/v1/drafts/{first_draft}/submit",
        json={"idempotency_key": "admin-submit"},
        headers=ADMIN,
    )
    test_client.app.state.container.erp_client.failure_mode = ERPFailureMode.SUCCESS
    assert submitted.status_code == 202
    assert test_client.post(
        f"/api/v1/submissions/{submitted.json()['submission_id']}/retry",
        headers=ADMIN,
    ).status_code == 201
    assert test_client.post(
        f"/api/v1/submissions/{submitted.json()['submission_id']}/reconcile",
        headers=ADMIN,
    ).status_code == 200

    second_draft = draft_id(test_client)
    assert test_client.post(
        f"/api/v1/drafts/{second_draft}/reject", headers=ADMIN
    ).status_code == 200


def test_401_403_and_409_use_one_error_shape() -> None:
    test_client = client()
    value = draft_id(test_client)
    unauthenticated = test_client.get(f"/api/v1/drafts/{value}")
    denied = test_client.post(f"/api/v1/drafts/{value}/approve", headers=VIEWER)
    conflict = test_client.post(
        f"/api/v1/drafts/{value}/submit",
        json={"idempotency_key": "not-approved"},
        headers=OPERATOR,
    )

    for response, status_code in (
        (unauthenticated, 401),
        (denied, 403),
        (conflict, 409),
    ):
        assert response.status_code == status_code
        assert set(response.json()["error"]) == {"code", "message"}


def test_applications_can_use_different_identity_providers() -> None:
    class StaticIdentityProvider:
        def __init__(self, actor: Actor) -> None:
            self.actor = actor

        def get_actor(self, actor_id: str | None, actor_role: str | None) -> Actor:
            return self.actor

    viewer_client = TestClient(
        create_app(create_container(StaticIdentityProvider(Actor(
            actor_id="fixed-viewer", role=ActorRole.VIEWER
        ))))
    )
    admin_client = TestClient(
        create_app(create_container(StaticIdentityProvider(Actor(
            actor_id="fixed-admin", role=ActorRole.ADMIN
        ))))
    )
    viewer_draft = draft_id(viewer_client)
    admin_draft = draft_id(admin_client)

    assert viewer_client.post(
        f"/api/v1/drafts/{viewer_draft}/approve"
    ).status_code == 403
    assert admin_client.post(
        f"/api/v1/drafts/{admin_draft}/approve"
    ).status_code == 200


def test_auth_modules_import_without_output() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import order_assistant.application.authorization; "
            "import order_assistant.infrastructure.identity; "
            "import order_assistant.api.dependencies",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
