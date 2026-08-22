import socket
import threading
import time

import httpx
import uvicorn

from erp_stub.app import app
from order_assistant.application.drafts import DraftService
from order_assistant.application.submissions import ResilientOrderService
from order_assistant.application.workflow import process_extracted_order
from order_assistant.domain import ExtractedOrder, SubmissionStatus
from order_assistant.infrastructure.demo_data import demo_inventory
from order_assistant.infrastructure.erp import FakeERPClient
from order_assistant.infrastructure.http_erp import HTTPERPClient
from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemorySubmissionRepository,
)
from order_assistant.infrastructure.unit_of_work import InMemoryUnitOfWorkFactory


TOKEN = "loopback-contract-token"


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def _approved(drafts: InMemoryDraftRepository):
    result = process_extracted_order(
        ExtractedOrder.model_validate(
            {
                "model": "6204",
                "quantity": 500,
                "primary_brand": "SKF",
                "fallback_brands": ["FAG"],
                "max_unit_price": "250",
                "delivery_deadline": "2026-08-17T09:00:00",
            }
        ),
        demo_inventory,
    )
    service = DraftService(drafts, FakeERPClient())
    created = service.create_draft(result)
    return service.approve_draft(created.draft_id, "manager@example.com")


def test_real_loopback_http_duplicate_and_timeout_reconciliation(monkeypatch) -> None:
    monkeypatch.setenv("ERP_STUB_TOKEN", TOKEN)
    monkeypatch.setenv("ERP_STUB_TIMEOUT_SECONDS", "0.15")
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started

    base_url = f"http://127.0.0.1:{port}"
    control_headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        with httpx.Client(base_url=base_url) as control:
            control.post(
                "/__test/mode",
                headers=control_headers,
                json={"mode": "SUCCESS", "reset": True},
            ).raise_for_status()

            drafts = InMemoryDraftRepository()
            submissions = InMemorySubmissionRepository()
            adapter = HTTPERPClient(
                base_url,
                TOKEN,
                read_timeout_seconds=0.05,
                allow_insecure_http=True,
            )
            service = ResilientOrderService(
                InMemoryUnitOfWorkFactory(drafts, submissions),
                adapter,
            )
            first_draft = _approved(drafts)
            first = service.submit_approved_draft(first_draft.draft_id, "loop-1")
            duplicate = service.submit_approved_draft(
                first_draft.draft_id,
                "loop-1",
            )
            stats = control.get("/__test/stats", headers=control_headers).json()
            assert first.status == SubmissionStatus.SUCCEEDED
            assert duplicate.created_order_id == first.created_order_id
            assert stats["actual_creation_count"] == 1

            control.post(
                "/__test/mode",
                headers=control_headers,
                json={"mode": "TIMEOUT_AFTER_CREATION"},
            ).raise_for_status()
            second_draft = _approved(drafts)
            unknown = service.submit_approved_draft(
                second_draft.draft_id,
                "loop-timeout",
            )
            assert unknown.status == SubmissionStatus.UNKNOWN
            control.post(
                "/__test/mode",
                headers=control_headers,
                json={"mode": "SUCCESS"},
            ).raise_for_status()
            reconciled = service.reconcile_submission(unknown.submission_id)
            stats = control.get("/__test/stats", headers=control_headers).json()
            assert reconciled.status == SubmissionStatus.SUCCEEDED
            assert stats["actual_creation_count"] == 2
            adapter.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()
