import subprocess
import sys

from fastapi.testclient import TestClient

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.domain import ERPFailureMode


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

VIEWER_HEADERS = {
    "X-Demo-Actor-Id": "viewer@example.com",
    "X-Demo-Actor-Role": "viewer",
}
MANAGER_HEADERS = {
    "X-Demo-Actor-Id": "manager@example.com",
    "X-Demo-Actor-Role": "manager",
}
OPERATOR_HEADERS = {
    "X-Demo-Actor-Id": "operator@example.com",
    "X-Demo-Actor-Role": "operator",
}


def create_client() -> TestClient:
    return TestClient(create_app(create_container()))


def create_draft(client: TestClient) -> str:
    response = client.post("/api/v1/order-requests", json=FULL_REQUEST)
    assert response.status_code == 201
    return response.json()["draft_id"]


def approve_draft(client: TestClient, draft_id: str) -> None:
    response = client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        headers=MANAGER_HEADERS,
    )
    assert response.status_code == 200


def test_health_returns_ok() -> None:
    response = create_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_full_request_returns_draft_ready_and_creates_draft() -> None:
    response = create_client().post("/api/v1/order-requests", json=FULL_REQUEST)

    assert response.status_code == 201
    assert response.json()["processing"]["status"] == "draft_ready"
    assert response.json()["draft_id"] is not None


def test_incomplete_request_needs_clarification_without_draft() -> None:
    response = create_client().post(
        "/api/v1/order-requests",
        json={**FULL_REQUEST, "quantity": None},
    )

    assert response.status_code == 200
    assert response.json()["processing"]["status"] == "needs_clarification"
    assert response.json()["draft_id"] is None


def test_no_match_does_not_create_draft() -> None:
    response = create_client().post(
        "/api/v1/order-requests",
        json={**FULL_REQUEST, "max_unit_price": "100"},
    )

    assert response.status_code == 200
    assert response.json()["processing"]["status"] == "no_match"
    assert response.json()["draft_id"] is None


def test_draft_can_be_retrieved_and_unknown_draft_returns_404() -> None:
    client = create_client()
    draft_id = create_draft(client)

    response = client.get(f"/api/v1/drafts/{draft_id}", headers=VIEWER_HEADERS)
    missing_response = client.get(
        "/api/v1/drafts/00000000-0000-0000-0000-000000000000",
        headers=VIEWER_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["draft_id"] == draft_id
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "draft_not_found"


def test_draft_can_be_approved() -> None:
    client = create_client()
    draft_id = create_draft(client)

    response = client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        headers=MANAGER_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_draft_can_be_rejected_and_cannot_be_approved_afterward() -> None:
    client = create_client()
    draft_id = create_draft(client)

    rejected = client.post(
        f"/api/v1/drafts/{draft_id}/reject",
        headers=MANAGER_HEADERS,
    )
    approved = client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        headers=MANAGER_HEADERS,
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert approved.status_code == 409


def test_submission_before_approval_returns_409() -> None:
    client = create_client()
    draft_id = create_draft(client)

    response = client.post(
        f"/api/v1/drafts/{draft_id}/submit",
        json={"idempotency_key": "submit-1"},
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_status_transition"


def test_approved_draft_creates_submission() -> None:
    client = create_client()
    draft_id = create_draft(client)
    approve_draft(client, draft_id)

    response = client.post(
        f"/api/v1/drafts/{draft_id}/submit",
        json={"idempotency_key": "submit-1"},
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"


def test_timeout_returns_unknown_and_retry_uses_saved_key() -> None:
    client = create_client()
    client.app.state.container.erp_client.failure_mode = (
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )
    draft_id = create_draft(client)
    approve_draft(client, draft_id)
    response = client.post(
        f"/api/v1/drafts/{draft_id}/submit",
        json={"idempotency_key": "timeout-key"},
        headers=OPERATOR_HEADERS,
    )
    client.app.state.container.erp_client.failure_mode = ERPFailureMode.SUCCESS

    retried = client.post(
        f"/api/v1/submissions/{response.json()['submission_id']}/retry",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 202
    assert response.json()["status"] == "unknown"
    assert retried.status_code == 201
    assert retried.json()["idempotency_key"].startswith("order-assistant-v1-")


def test_reconciliation_finishes_timeout_after_creation_without_duplicate() -> None:
    client = create_client()
    client.app.state.container.erp_client.failure_mode = (
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )
    draft_id = create_draft(client)
    approve_draft(client, draft_id)
    submitted = client.post(
        f"/api/v1/drafts/{draft_id}/submit",
        json={"idempotency_key": "after-create-key"},
        headers=OPERATOR_HEADERS,
    )

    reconciled = client.post(
        f"/api/v1/submissions/{submitted.json()['submission_id']}/reconcile",
        headers=OPERATOR_HEADERS,
    )

    assert submitted.status_code == 202
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "succeeded"
    assert client.app.state.container.erp_client.actual_creation_count == 1


def test_repeated_submission_does_not_create_second_erp_order() -> None:
    client = create_client()
    draft_id = create_draft(client)
    approve_draft(client, draft_id)
    first = client.post(
        f"/api/v1/drafts/{draft_id}/submit",
        json={"idempotency_key": "submit-1"},
        headers=OPERATOR_HEADERS,
    )
    repeated = client.post(
        f"/api/v1/drafts/{draft_id}/submit",
        json={"idempotency_key": "client-cannot-replace-server-key"},
        headers=OPERATOR_HEADERS,
    )

    assert repeated.status_code == 201
    assert repeated.json()["idempotency_key"] == first.json()["idempotency_key"]
    assert client.app.state.container.erp_client.actual_creation_count == 1


def test_unknown_submission_and_invalid_data_return_expected_errors() -> None:
    client = create_client()
    missing = client.get(
        "/api/v1/submissions/00000000-0000-0000-0000-000000000000",
        headers=VIEWER_HEADERS,
    )
    invalid_quantity = client.post(
        "/api/v1/order-requests",
        json={**FULL_REQUEST, "quantity": 0},
    )
    invalid_price = client.post(
        "/api/v1/order-requests",
        json={**FULL_REQUEST, "max_unit_price": "-1"},
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "submission_not_found"
    assert invalid_quantity.status_code == 422
    assert invalid_price.status_code == 422
    assert invalid_quantity.json()["error"] == {
        "code": "validation_error",
        "message": "Request validation failed.",
    }


def test_two_applications_do_not_share_in_memory_state() -> None:
    first_client = create_client()
    second_client = create_client()
    draft_id = create_draft(first_client)

    response = second_client.get(f"/api/v1/drafts/{draft_id}", headers=VIEWER_HEADERS)

    assert response.status_code == 404


def test_api_import_produces_no_output() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import order_assistant.api.app"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
