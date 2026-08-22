from pathlib import Path

from fastapi.testclient import TestClient

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.config import Settings
from order_assistant.infrastructure.database.base import Base


def test_sqlalchemy_api_persists_draft_after_container_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'api.db'}"
    settings = Settings(persistence_backend="sqlalchemy", database_url=url)
    first = create_container(settings=settings)
    Base.metadata.create_all(first.engine)
    client = TestClient(create_app(first))
    payload = {
        "model": "6204", "quantity": 500, "primary_brand": "SKF",
        "fallback_brands": ["FAG"], "max_unit_price": "250",
        "delivery_deadline": "2026-08-15T09:00:00",
    }
    created = client.post("/api/v1/order-requests", json=payload).json()
    draft_id = created["draft_id"]
    headers = {"X-Demo-Actor-Id": "manager@example.com", "X-Demo-Actor-Role": "manager"}
    assert client.post(f"/api/v1/drafts/{draft_id}/approve", headers=headers).status_code == 200
    first.dispose()

    second = create_container(settings=settings)
    restored = TestClient(create_app(second)).get(
        f"/api/v1/drafts/{draft_id}", headers=headers
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "approved"
    assert restored.json()["approved_by"] == "manager@example.com"
    second.dispose()
