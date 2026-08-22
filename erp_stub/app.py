import os
import time
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StubMode(str, Enum):
    SUCCESS = "SUCCESS"
    TIMEOUT_BEFORE_CREATION = "TIMEOUT_BEFORE_CREATION"
    TIMEOUT_AFTER_CREATION = "TIMEOUT_AFTER_CREATION"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_JSON = "INVALID_JSON"
    MALFORMED_SUCCESS = "MALFORMED_SUCCESS"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class StubOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_reference: UUID
    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    currency: str
    requested_delivery_at: datetime
    approved_by: str = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def require_uah(cls, value: str) -> str:
        if value != "UAH":
            raise ValueError("currency must be UAH")
        return value

class ModeRequest(BaseModel):
    mode: StubMode
    reset: bool = False


app = FastAPI(title="Independent Local ERP Stub", docs_url=None, redoc_url=None)
_lock = Lock()
_orders: dict[str, dict[str, str]] = {}
_payloads: dict[str, dict[str, object]] = {}
_actual_creation_count = 0
_mode = StubMode(os.getenv("ERP_STUB_MODE", StubMode.SUCCESS.value))


def _token() -> str:
    return os.getenv("ERP_STUB_TOKEN", "local-erp-stub-token")


def _delay() -> float:
    return float(os.getenv("ERP_STUB_TIMEOUT_SECONDS", "2"))


def _authorize(authorization: str | None) -> None:
    if authorization != f"Bearer {_token()}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def _order_response(key: str) -> dict[str, str]:
    return _orders[key]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/orders")
def create_order(
    request: StubOrderRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    correlation_id: UUID = Header(alias="X-Correlation-ID"),
) -> Response:
    del correlation_id
    global _actual_creation_count
    _authorize(authorization)
    mode = _mode
    if mode == StubMode.UNAUTHORIZED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if mode == StubMode.TIMEOUT_BEFORE_CREATION:
        time.sleep(_delay())
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT)
    if mode == StubMode.RATE_LIMITED:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    if mode == StubMode.SERVER_ERROR:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    if mode == StubMode.IDEMPOTENCY_CONFLICT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    payload = request.model_dump(mode="json")
    with _lock:
        existing = _orders.get(idempotency_key)
        if existing is not None:
            if _payloads[idempotency_key] != payload:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT)
            return JSONResponse(existing, status_code=status.HTTP_200_OK)
        order = {
            "order_id": f"STUB-ORDER-{uuid4()}",
            "status": "created",
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _orders[idempotency_key] = order
        _payloads[idempotency_key] = payload
        _actual_creation_count += 1

    if mode == StubMode.TIMEOUT_AFTER_CREATION:
        time.sleep(_delay())
    if mode == StubMode.INVALID_JSON:
        return PlainTextResponse(
            "{invalid-json",
            status_code=status.HTTP_201_CREATED,
            media_type="application/json",
        )
    if mode == StubMode.MALFORMED_SUCCESS:
        return JSONResponse(
            {"order_id": order["order_id"], "status": "created"},
            status_code=status.HTTP_201_CREATED,
        )
    return JSONResponse(order, status_code=status.HTTP_201_CREATED)


@app.get("/api/v1/orders/by-idempotency-key/{key}")
def lookup_order(
    key: str,
    authorization: str | None = Header(default=None),
    correlation_id: UUID = Header(alias="X-Correlation-ID"),
) -> dict[str, str]:
    del correlation_id
    _authorize(authorization)
    mode = _mode
    if mode == StubMode.UNAUTHORIZED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if mode == StubMode.RATE_LIMITED:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    if mode == StubMode.SERVER_ERROR:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    try:
        return _order_response(key)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@app.post("/__test/mode")
def set_mode(
    request: ModeRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(authorization)
    global _mode, _actual_creation_count
    with _lock:
        _mode = request.mode
        if request.reset:
            _orders.clear()
            _payloads.clear()
            _actual_creation_count = 0
    return {"mode": _mode.value, "actual_creation_count": _actual_creation_count}


@app.get("/__test/stats")
def stats(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(authorization)
    return {
        "mode": _mode.value,
        "actual_creation_count": _actual_creation_count,
        "stored_order_count": len(_orders),
    }
