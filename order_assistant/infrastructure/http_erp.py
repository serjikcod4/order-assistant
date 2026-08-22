from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from time import monotonic
from typing import Literal
from urllib.parse import quote, urlparse
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from order_assistant.application.ports import ERPCallMetadata
from order_assistant.domain import (
    CreatedOrder,
    DraftStatus,
    ERPAuthenticationError,
    ERPConflictError,
    ERPContractError,
    ERPPermanentError,
    ERPRateLimitedError,
    ERPTimeoutError,
    ERPUnavailableError,
    InvalidDraftResultError,
    OrderDraft,
)


MAX_ERP_RESPONSE_BYTES = 64 * 1024


class _ERPOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=255)
    status: Literal["created"]
    idempotency_key: str = Field(min_length=1, max_length=255)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware.")
        return value


class HTTPERPClient:
    """Synchronous ERP v1 adapter with no automatic POST retry."""

    backend = "http"
    provider = "http_erp"

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        contract_version: str = "v1",
        connect_timeout_seconds: float = 3,
        read_timeout_seconds: float = 10,
        write_timeout_seconds: float = 5,
        pool_timeout_seconds: float = 3,
        allow_insecure_http: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.contract_version = contract_version
        self._validate_configuration(
            base_url,
            token,
            contract_version,
            allow_insecure_http,
        )
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=write_timeout_seconds,
                pool=pool_timeout_seconds,
            ),
        )
        self._base_url = base_url.rstrip("/")
        self._correlation_id: ContextVar[UUID | None] = ContextVar(
            "erp_correlation_id",
            default=None,
        )
        self._draft_context: ContextVar[OrderDraft | None] = ContextVar(
            "erp_draft_context",
            default=None,
        )
        self._last_metadata: ContextVar[ERPCallMetadata | None] = ContextVar(
            "erp_call_metadata",
            default=None,
        )
        self._orders: dict[str, CreatedOrder] = {}

    def set_call_context(
        self,
        correlation_id: UUID,
        draft: OrderDraft,
    ) -> None:
        self._correlation_id.set(correlation_id)
        self._draft_context.set(draft.model_copy(deep=True))

    def set_correlation_id(self, correlation_id: UUID) -> None:
        self._correlation_id.set(correlation_id)

    def get_last_call_metadata(self) -> ERPCallMetadata | None:
        return self._last_metadata.get()

    def create_order(
        self,
        draft: OrderDraft,
        idempotency_key: str,
    ) -> CreatedOrder:
        self._require_approved_draft(draft)
        self._draft_context.set(draft.model_copy(deep=True))
        payload = self._payload(draft)
        response = self._send(
            "POST",
            "/api/v1/orders",
            idempotency_key=idempotency_key,
            json=payload,
        )
        self._classify_create_status(response.status_code)
        dto = self._validate_success(response, idempotency_key)
        order = self._to_domain(dto, draft)
        self._orders[order.order_id] = order
        return order

    def get_order_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CreatedOrder | None:
        response = self._send(
            "GET",
            "/api/v1/orders/by-idempotency-key/"
            f"{quote(idempotency_key, safe='')}",
            idempotency_key=idempotency_key,
        )
        if response.status_code == 404:
            self._replace_error_code("erp_order_not_found")
            return None
        self._classify_lookup_status(response.status_code)
        dto = self._validate_success(response, idempotency_key)
        draft = self._draft_context.get()
        if draft is None:
            raise ERPContractError(
                "ERP lookup succeeded without approved draft context."
            )
        order = self._to_domain(dto, draft)
        self._orders[order.order_id] = order
        return order

    def get_order(self, order_id: str) -> CreatedOrder:
        try:
            return self._orders[order_id]
        except KeyError as error:
            raise KeyError(order_id) from error

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _send(
        self,
        method: str,
        path: str,
        *,
        idempotency_key: str,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        correlation_id = self._correlation_id.get() or uuid4()
        self._correlation_id.set(correlation_id)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Idempotency-Key": idempotency_key,
            "X-Correlation-ID": str(correlation_id),
            "Accept": "application/json",
        }
        started = monotonic()
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json,
            )
        except httpx.TimeoutException as error:
            self._save_metadata(
                correlation_id,
                started,
                error_code=ERPTimeoutError.code,
            )
            raise ERPTimeoutError("ERP request timed out.") from error
        except httpx.RequestError as error:
            self._save_metadata(
                correlation_id,
                started,
                error_code=ERPUnavailableError.code,
            )
            raise ERPUnavailableError("ERP is unavailable.") from error
        self._save_metadata(
            correlation_id,
            started,
            http_status=response.status_code,
        )
        return response

    def _validate_success(
        self,
        response: httpx.Response,
        idempotency_key: str,
    ) -> _ERPOrderResponse:
        if len(response.content) > MAX_ERP_RESPONSE_BYTES:
            self._replace_error_code(ERPContractError.code)
            raise ERPContractError("ERP response exceeds the size limit.")
        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().casefold()
        if media_type != "application/json" and not media_type.endswith("+json"):
            self._replace_error_code(ERPContractError.code)
            raise ERPContractError("ERP success response is not JSON.")
        try:
            dto = _ERPOrderResponse.model_validate_json(response.content)
        except (ValueError, TypeError) as error:
            self._replace_error_code(ERPContractError.code)
            raise ERPContractError(
                "ERP success response violates contract v1."
            ) from error
        if dto.idempotency_key != idempotency_key:
            self._replace_error_code(ERPContractError.code)
            raise ERPContractError(
                "ERP returned a mismatched idempotency key."
            )
        return dto

    def _classify_create_status(self, status_code: int) -> None:
        if status_code in {200, 201}:
            return
        self._raise_for_status(status_code)

    def _classify_lookup_status(self, status_code: int) -> None:
        if status_code == 200:
            return
        self._raise_for_status(status_code)

    def _raise_for_status(self, status_code: int) -> None:
        if status_code == 429:
            self._replace_error_code(ERPRateLimitedError.code)
            raise ERPRateLimitedError("ERP rate limit was reached.")
        if status_code >= 500:
            self._replace_error_code(ERPUnavailableError.code)
            raise ERPUnavailableError("ERP returned a server error.")
        if status_code in {401, 403}:
            self._replace_error_code(ERPAuthenticationError.code)
            raise ERPAuthenticationError("ERP authentication was rejected.")
        if status_code == 409:
            self._replace_error_code(ERPConflictError.code)
            raise ERPConflictError("ERP idempotency conflict requires review.")
        if status_code in {400, 422}:
            self._replace_error_code(ERPPermanentError.code)
            raise ERPPermanentError("ERP rejected the approved order payload.")
        self._replace_error_code(ERPPermanentError.code)
        raise ERPPermanentError(
            f"ERP returned unsupported HTTP status {status_code}."
        )

    def _payload(self, draft: OrderDraft) -> dict[str, object]:
        result = draft.processing_result
        item = result.selected_item
        requirements = result.requirements
        if item is None or requirements is None:
            raise InvalidDraftResultError(
                "Draft has no selected item to create."
            )
        return {
            "external_reference": str(draft.draft_id),
            "sku": item.sku,
            "quantity": requirements.quantity,
            "unit_price": self._decimal_string(item.unit_price),
            "currency": "UAH",
            "requested_delivery_at": requirements.delivery_deadline.isoformat(),
            "approved_by": draft.approved_by,
        }

    def _to_domain(
        self,
        dto: _ERPOrderResponse,
        draft: OrderDraft,
    ) -> CreatedOrder:
        result = draft.processing_result
        item = result.selected_item
        requirements = result.requirements
        if item is None or requirements is None:
            raise InvalidDraftResultError(
                "Draft has no selected item to create."
            )
        return CreatedOrder(
            order_id=dto.order_id,
            draft_id=draft.draft_id,
            sku=item.sku,
            quantity=requirements.quantity,
            unit_price=item.unit_price,
            total_price=item.unit_price * requirements.quantity,
            idempotency_key=dto.idempotency_key,
            created_at=dto.created_at,
        )

    def _save_metadata(
        self,
        correlation_id: UUID,
        started: float,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self._last_metadata.set(
            ERPCallMetadata(
                backend=self.backend,
                provider=self.provider,
                contract_version=self.contract_version,
                correlation_id=correlation_id,
                http_status=http_status,
                error_code=error_code,
                duration_ms=max(0, round((monotonic() - started) * 1000)),
            )
        )

    def _replace_error_code(self, error_code: str) -> None:
        metadata = self._last_metadata.get()
        if metadata is None:
            return
        self._last_metadata.set(
            ERPCallMetadata(
                backend=metadata.backend,
                provider=metadata.provider,
                contract_version=metadata.contract_version,
                correlation_id=metadata.correlation_id,
                http_status=metadata.http_status,
                error_code=error_code,
                duration_ms=metadata.duration_ms,
            )
        )

    @staticmethod
    def _decimal_string(value: Decimal) -> str:
        return format(value, "f")

    @staticmethod
    def _require_approved_draft(draft: OrderDraft) -> None:
        if draft.status != DraftStatus.APPROVED or not draft.approved_by:
            raise ERPPermanentError(
                "Only a human-approved draft can be sent to ERP."
            )

    @staticmethod
    def _validate_configuration(
        base_url: str,
        token: str,
        contract_version: str,
        allow_insecure_http: bool,
    ) -> None:
        if not token.strip():
            raise ValueError("ERP token is required for HTTP backend.")
        if contract_version != "v1":
            raise ValueError("Only ERP contract version v1 is supported.")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ERP base URL must be an absolute HTTP(S) URL.")
        if parsed.scheme == "http" and not allow_insecure_http:
            raise ValueError(
                "Insecure ERP HTTP requires explicit allow_insecure_http=true."
            )
