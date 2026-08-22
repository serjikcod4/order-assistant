import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from order_assistant.application.drafts import DraftService
from order_assistant.application.submissions import ResilientOrderService
from order_assistant.application.workflow import process_extracted_order
from order_assistant.domain import (
    ERPAuthenticationError,
    ERPConflictError,
    ERPContractError,
    ERPPermanentError,
    ERPRateLimitedError,
    ERPTimeoutError,
    ERPUnavailableError,
    ExtractedOrder,
    SubmissionStatus,
)
from order_assistant.infrastructure.demo_data import demo_inventory
from order_assistant.infrastructure.erp import FakeERPClient
from order_assistant.infrastructure.http_erp import (
    HTTPERPClient,
    MAX_ERP_RESPONSE_BYTES,
)
from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemorySubmissionRepository,
)
from order_assistant.infrastructure.unit_of_work import InMemoryUnitOfWorkFactory


TOKEN = "contract-test-token"


def approved_draft(drafts: InMemoryDraftRepository | None = None):
    drafts = drafts or InMemoryDraftRepository()
    extracted = ExtractedOrder.model_validate(
        {
            "model": "6204",
            "quantity": 500,
            "primary_brand": "SKF",
            "fallback_brands": ["FAG"],
            "max_unit_price": "250",
            "delivery_deadline": "2026-08-15T09:00:00",
        }
    )
    result = process_extracted_order(extracted, demo_inventory)
    service = DraftService(drafts, FakeERPClient())
    draft = service.create_draft(result)
    return drafts, service.approve_draft(draft.draft_id, "manager@example.com")


def response_payload(key: str, **updates) -> dict[str, str]:
    payload = {
        "order_id": "ERP-1001",
        "status": "created",
        "idempotency_key": key,
        "created_at": "2026-08-16T10:30:00+00:00",
    }
    payload.update(updates)
    return payload


def client(handler) -> HTTPERPClient:
    transport = httpx.MockTransport(handler)
    injected = httpx.Client(transport=transport)
    return HTTPERPClient(
        "http://erp.local",
        TOKEN,
        allow_insecure_http=True,
        client=injected,
    )


def test_create_sends_minimal_approved_payload_and_required_headers() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            201,
            json=response_payload(request.headers["Idempotency-Key"]),
        )

    adapter = client(handler)
    _, draft = approved_draft()
    correlation_id = uuid4()
    adapter.set_call_context(correlation_id, draft)
    order = adapter.create_order(draft, "stable-key")

    assert order.order_id == "ERP-1001"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["headers"]["Idempotency-Key"] == "stable-key"
    assert UUID(captured["headers"]["X-Correlation-ID"]) == correlation_id
    assert captured["payload"] == {
        "external_reference": str(draft.draft_id),
        "sku": "SKU-23",
        "quantity": 500,
        "unit_price": "240",
        "currency": "UAH",
        "requested_delivery_at": "2026-08-15T09:00:00",
        "approved_by": "manager@example.com",
    }
    forbidden = {
        "source_text",
        "prompt",
        "reasoning",
        "audit_hmac",
        "processing_result",
    }
    assert forbidden.isdisjoint(captured["payload"])


def test_idempotent_201_then_200_returns_same_order() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201 if calls == 1 else 200,
            json=response_payload(request.headers["Idempotency-Key"]),
        )

    adapter = client(handler)
    _, draft = approved_draft()
    adapter.set_call_context(uuid4(), draft)
    first = adapter.create_order(draft, "same-key")
    second = adapter.create_order(draft, "same-key")
    assert first == second
    assert calls == 2


def test_lookup_success_and_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("missing"):
            return httpx.Response(404)
        return httpx.Response(200, json=response_payload("known"))

    adapter = client(handler)
    _, draft = approved_draft()
    adapter.set_call_context(uuid4(), draft)
    assert adapter.get_order_by_idempotency_key("known").order_id == "ERP-1001"
    assert adapter.get_order_by_idempotency_key("missing") is None


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (429, ERPRateLimitedError),
        (500, ERPUnavailableError),
        (401, ERPAuthenticationError),
        (403, ERPAuthenticationError),
        (409, ERPConflictError),
        (400, ERPPermanentError),
        (422, ERPPermanentError),
    ],
)
def test_create_classifies_http_errors(status_code, error_type) -> None:
    adapter = client(lambda request: httpx.Response(status_code))
    _, draft = approved_draft()
    adapter.set_call_context(uuid4(), draft)
    with pytest.raises(error_type) as captured:
        adapter.create_order(draft, "key")
    assert TOKEN not in str(captured.value)
    assert "Authorization" not in str(captured.value)


def test_timeout_and_network_errors_are_distinct_and_safe() -> None:
    _, draft = approved_draft()
    for raised, expected in [
        (httpx.ReadTimeout("secret URL omitted"), ERPTimeoutError),
        (httpx.ConnectError("secret URL omitted"), ERPUnavailableError),
    ]:
        adapter = client(lambda request, error=raised: (_ for _ in ()).throw(error))
        adapter.set_call_context(uuid4(), draft)
        with pytest.raises(expected) as captured:
            adapter.create_order(draft, "key")
        assert TOKEN not in str(captured.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, content=b"{broken", headers={"content-type": "application/json"}),
        httpx.Response(201, json={"order_id": "only-one-field"}),
        httpx.Response(201, json=response_payload("wrong-key")),
        httpx.Response(201, text="not-json", headers={"content-type": "text/plain"}),
        httpx.Response(
            201,
            content=b"x" * (MAX_ERP_RESPONSE_BYTES + 1),
            headers={"content-type": "application/json"},
        ),
        httpx.Response(
            201,
            json=response_payload("key", created_at="2026-08-16T10:30:00"),
        ),
        httpx.Response(201, json=response_payload("key", status="accepted")),
    ],
)
def test_malformed_success_is_contract_error(response: httpx.Response) -> None:
    adapter = client(lambda request: response)
    _, draft = approved_draft()
    adapter.set_call_context(uuid4(), draft)
    with pytest.raises(ERPContractError):
        adapter.create_order(draft, "key")


def test_service_maps_uncertain_and_permanent_http_outcomes() -> None:
    cases = [
        (429, SubmissionStatus.UNKNOWN, "erp_rate_limited"),
        (500, SubmissionStatus.UNKNOWN, "erp_unavailable"),
        (401, SubmissionStatus.PERMANENTLY_FAILED, "erp_authentication_failed"),
        (409, SubmissionStatus.PERMANENTLY_FAILED, "erp_idempotency_conflict"),
    ]
    for status_code, expected_status, error_code in cases:
        drafts, draft = approved_draft()
        submissions = InMemorySubmissionRepository()
        factory = InMemoryUnitOfWorkFactory(drafts, submissions)
        adapter = client(lambda request, code=status_code: httpx.Response(code))
        submission = ResilientOrderService(factory, adapter).submit_approved_draft(
            draft.draft_id,
            f"key-{status_code}",
        )
        assert submission.status == expected_status
        assert submission.normalized_error_code == error_code
        assert submission.last_http_status == status_code
        assert submission.erp_backend == "http"
        assert submission.erp_call_duration_ms is not None


def test_malformed_2xx_becomes_unknown_because_creation_may_have_happened() -> None:
    drafts, draft = approved_draft()
    submissions = InMemorySubmissionRepository()
    adapter = client(lambda request: httpx.Response(201, json={"bad": "shape"}))
    result = ResilientOrderService(
        InMemoryUnitOfWorkFactory(drafts, submissions),
        adapter,
    ).submit_approved_draft(draft.draft_id, "uncertain-key")
    assert result.status == SubmissionStatus.UNKNOWN
    assert result.normalized_error_code == "erp_contract_error"


def test_timeout_after_creation_is_reconciled_without_second_post() -> None:
    drafts, draft = approved_draft()
    submissions = InMemorySubmissionRepository()
    stored = {}
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "POST":
            post_count += 1
            key = request.headers["Idempotency-Key"]
            stored[key] = response_payload(key)
            raise httpx.ReadTimeout("response lost after durable creation")
        key = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=stored[key])

    service = ResilientOrderService(
        InMemoryUnitOfWorkFactory(drafts, submissions),
        client(handler),
    )
    unknown = service.submit_approved_draft(draft.draft_id, "timeout-key")
    reconciled = service.reconcile_submission(unknown.submission_id)

    assert unknown.status == SubmissionStatus.UNKNOWN
    assert reconciled.status == SubmissionStatus.SUCCEEDED
    assert reconciled.created_order_id == "ERP-1001"
    assert post_count == 1


@pytest.mark.parametrize(
    ("lookup_response", "expected_code"),
    [
        (httpx.Response(500), "erp_unavailable"),
        (httpx.Response(200, json={"bad": "shape"}), "erp_contract_error"),
    ],
)
def test_failed_reconciliation_preserves_unknown_and_never_posts_again(
    lookup_response: httpx.Response,
    expected_code: str,
) -> None:
    drafts, draft = approved_draft()
    submissions = InMemorySubmissionRepository()
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "POST":
            post_count += 1
            raise httpx.ReadTimeout("unknown create result")
        return lookup_response

    service = ResilientOrderService(
        InMemoryUnitOfWorkFactory(drafts, submissions),
        client(handler),
    )
    unknown = service.submit_approved_draft(draft.draft_id, "lookup-failure")
    reconciled = service.reconcile_submission(unknown.submission_id)
    assert reconciled.status == SubmissionStatus.UNKNOWN
    assert reconciled.normalized_error_code == expected_code
    assert post_count == 1


class TrackingFactory:
    def __init__(self, factory) -> None:
        self.factory = factory
        self.active_count = 0
        self.events = []

    def __call__(self):
        parent = self
        inner = self.factory()

        class Tracked:
            def __enter__(self):
                parent.active_count += 1
                parent.events.append("uow_enter")
                value = inner.__enter__()
                self.drafts = value.drafts
                self.submissions = value.submissions
                return self

            def commit(self):
                parent.events.append("uow_commit")
                return inner.commit()

            def rollback(self):
                return inner.rollback()

            def __exit__(self, *args):
                parent.active_count -= 1
                parent.events.append("uow_exit")
                return inner.__exit__(*args)

        return Tracked()


def test_http_and_reconciliation_run_with_zero_active_uow_and_no_duplicate(
    monkeypatch,
) -> None:
    drafts, draft = approved_draft()
    submissions = InMemorySubmissionRepository()
    tracking = TrackingFactory(InMemoryUnitOfWorkFactory(drafts, submissions))
    stored = {}
    create_count = 0
    seen_correlations = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_count
        assert tracking.active_count == 0
        seen_correlations.append(request.headers["X-Correlation-ID"])
        if request.method == "POST":
            create_count += 1
            key = request.headers["Idempotency-Key"]
            stored[key] = response_payload(key)
            return httpx.Response(201, json=stored[key])
        key = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=stored[key])

    adapter = client(handler)
    service = ResilientOrderService(tracking, adapter)
    monkeypatch.setattr(
        service,
        "_success",
        lambda *args: (_ for _ in ()).throw(RuntimeError("simulated crash")),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.submit_approved_draft(draft.draft_id, "crash-key")
    pending = submissions.find_by_draft_id(draft.draft_id)
    assert pending.status == SubmissionStatus.PENDING

    recovered = ResilientOrderService(tracking, adapter).reconcile_submission(
        pending.submission_id
    )
    assert recovered.status == SubmissionStatus.SUCCEEDED
    assert create_count == 1
    assert len(set(seen_correlations)) == 1
    assert tracking.events.index("uow_commit") < tracking.events.index("uow_exit")


def test_http_configuration_requires_token_and_explicit_insecure_opt_in() -> None:
    with pytest.raises(ValueError, match="token"):
        HTTPERPClient("https://erp.example", "")
    with pytest.raises(ValueError, match="allow_insecure"):
        HTTPERPClient("http://localhost:8080", TOKEN)
