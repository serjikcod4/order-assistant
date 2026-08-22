from datetime import datetime, timezone
from uuid import uuid4

from order_assistant.domain import (
    CreatedOrder,
    ERPPermanentError,
    ERPFailureMode,
    ERPTimeoutError,
    InvalidDraftResultError,
    OrderDraft,
)


class FakeERPClient:
    """Offline ERP test double for approved drafts."""

    backend = "fake"
    provider = "in_memory"
    contract_version = "v1"

    def __init__(self) -> None:
        self.orders: dict[str, CreatedOrder] = {}
        self.orders_by_idempotency_key: dict[str, CreatedOrder] = {}
        self.create_call_count = 0

    def create_order(
        self,
        draft: OrderDraft,
        idempotency_key: str,
    ) -> CreatedOrder:
        existing = self.orders_by_idempotency_key.get(idempotency_key)
        if existing is not None:
            return existing
        result = draft.processing_result
        if result.selected_item is None or result.requirements is None:
            raise InvalidDraftResultError("Draft has no selected item to create.")
        created_order = CreatedOrder(
            order_id=f"TEST-ORDER-{uuid4()}",
            draft_id=draft.draft_id,
            sku=result.selected_item.sku,
            quantity=result.requirements.quantity,
            unit_price=result.selected_item.unit_price,
            total_price=result.selected_item.unit_price * result.requirements.quantity,
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc),
        )
        self.orders[created_order.order_id] = created_order
        self.orders_by_idempotency_key[idempotency_key] = created_order
        self.create_call_count += 1
        return created_order

    def get_order_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CreatedOrder | None:
        return self.orders_by_idempotency_key.get(idempotency_key)

    def get_order(self, order_id: str) -> CreatedOrder:
        for order in self.orders_by_idempotency_key.values():
            if order.order_id == order_id:
                return order
        raise KeyError(order_id)


class ResilientFakeERPClient:
    """In-memory ERP double that simulates timeout positions."""

    backend = "fake"
    provider = "in_memory"
    contract_version = "v1"

    def __init__(self, failure_mode: ERPFailureMode = ERPFailureMode.SUCCESS) -> None:
        self.failure_mode = failure_mode
        self.orders_by_idempotency_key: dict[str, CreatedOrder] = {}
        self.actual_creation_count = 0

    def create_order(
        self,
        draft: OrderDraft,
        idempotency_key: str,
    ) -> CreatedOrder:
        existing = self.orders_by_idempotency_key.get(idempotency_key)
        if existing is not None:
            return existing
        if self.failure_mode == ERPFailureMode.TIMEOUT_BEFORE_CREATION:
            raise ERPTimeoutError("ERP timed out before creating the order.")
        if self.failure_mode == ERPFailureMode.PERMANENT_FAILURE:
            raise ERPPermanentError("ERP rejected the order permanently.")
        result = draft.processing_result
        if result.selected_item is None or result.requirements is None:
            raise ERPPermanentError("Draft has no item available for ERP creation.")
        created_order = CreatedOrder(
            order_id=f"TEST-ORDER-{uuid4()}",
            draft_id=draft.draft_id,
            sku=result.selected_item.sku,
            quantity=result.requirements.quantity,
            unit_price=result.selected_item.unit_price,
            total_price=result.selected_item.unit_price * result.requirements.quantity,
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc),
        )
        self.orders_by_idempotency_key[idempotency_key] = created_order
        self.actual_creation_count += 1
        if self.failure_mode == ERPFailureMode.TIMEOUT_AFTER_CREATION:
            raise ERPTimeoutError("ERP timed out after creating the order.")
        return created_order

    def get_order_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> CreatedOrder | None:
        return self.orders_by_idempotency_key.get(idempotency_key)

    def get_order(self, order_id: str) -> CreatedOrder:
        for order in self.orders_by_idempotency_key.values():
            if order.order_id == order_id:
                return order
        raise KeyError(order_id)
