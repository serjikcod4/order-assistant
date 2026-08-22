from uuid import uuid4

from fastapi.testclient import TestClient

from erp_stub.app import app


TOKEN = "local-erp-stub-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def headers(key: str) -> dict[str, str]:
    return {
        **AUTH,
        "Idempotency-Key": key,
        "X-Correlation-ID": str(uuid4()),
    }


def payload(**updates) -> dict[str, object]:
    value = {
        "external_reference": str(uuid4()),
        "sku": "SKU-23",
        "quantity": 500,
        "unit_price": "240",
        "currency": "UAH",
        "requested_delivery_at": "2026-08-15T09:00:00",
        "approved_by": "manager@example.com",
    }
    value.update(updates)
    return value


def reset(client: TestClient) -> None:
    response = client.post(
        "/__test/mode",
        headers=AUTH,
        json={"mode": "SUCCESS", "reset": True},
    )
    assert response.status_code == 200


def test_stub_auth_idempotency_conflict_lookup_and_creation_count() -> None:
    with TestClient(app) as client:
        reset(client)
        body = payload()
        first = client.post("/api/v1/orders", headers=headers("key"), json=body)
        repeated = client.post("/api/v1/orders", headers=headers("key"), json=body)
        conflict = client.post(
            "/api/v1/orders",
            headers=headers("key"),
            json={**body, "quantity": 501},
        )
        found = client.get(
            "/api/v1/orders/by-idempotency-key/key",
            headers=headers("key"),
        )
        missing = client.get(
            "/api/v1/orders/by-idempotency-key/missing",
            headers=headers("missing"),
        )
        stats = client.get("/__test/stats", headers=AUTH)

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert conflict.status_code == 409
    assert found.json() == first.json()
    assert missing.status_code == 404
    assert stats.json()["actual_creation_count"] == 1


def test_stub_requires_bearer_and_supports_controlled_modes() -> None:
    with TestClient(app) as client:
        reset(client)
        unauthenticated = headers("unauthenticated")
        unauthenticated.pop("Authorization")
        assert client.post(
            "/api/v1/orders",
            headers=unauthenticated,
            json=payload(),
        ).status_code == 401
        for mode, expected in [
            ("RATE_LIMITED", 429),
            ("SERVER_ERROR", 500),
            ("UNAUTHORIZED", 401),
            ("IDEMPOTENCY_CONFLICT", 409),
        ]:
            client.post("/__test/mode", headers=AUTH, json={"mode": mode})
            result = client.post(
                "/api/v1/orders",
                headers=headers(f"key-{mode}"),
                json=payload(),
            )
            assert result.status_code == expected


def test_stub_can_emit_invalid_json_and_malformed_success() -> None:
    with TestClient(app) as client:
        for mode in ("INVALID_JSON", "MALFORMED_SUCCESS"):
            reset(client)
            client.post("/__test/mode", headers=AUTH, json={"mode": mode})
            result = client.post(
                "/api/v1/orders",
                headers=headers(f"key-{mode}"),
                json=payload(),
            )
            assert result.status_code == 201
            if mode == "INVALID_JSON":
                assert result.headers["content-type"].startswith("application/json")
                assert result.text == "{invalid-json"
            else:
                assert "idempotency_key" not in result.json()
