"""Lesson 21: production-shaped HTTP ERP boundary and local contract stub."""

from order_assistant.application.ports import ERPClient
from order_assistant.domain import (
    ERPAuthenticationError,
    ERPConflictError,
    ERPContractError,
    ERPPermanentError,
    ERPRateLimitedError,
    ERPTimeoutError,
    ERPUnavailableError,
)
from order_assistant.infrastructure.erp import (
    FakeERPClient,
    ResilientFakeERPClient,
)
from order_assistant.infrastructure.http_erp import HTTPERPClient


def main() -> None:
    print("ERP backend defaults to FakeERP; HTTPERPClient is opt-in.")
    print("Contract: docs/contracts/erp-v1.openapi.yaml")


if __name__ == "__main__":
    main()


__all__ = [
    "ERPAuthenticationError",
    "ERPClient",
    "ERPConflictError",
    "ERPContractError",
    "ERPPermanentError",
    "ERPRateLimitedError",
    "ERPTimeoutError",
    "ERPUnavailableError",
    "FakeERPClient",
    "HTTPERPClient",
    "ResilientFakeERPClient",
]
