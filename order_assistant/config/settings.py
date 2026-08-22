from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "production"] = "development"
    identity_provider: Literal["demo_headers"] = "demo_headers"
    persistence_backend: Literal["memory", "sqlalchemy"] = "memory"
    database_url: str | None = None
    erp_backend: Literal["fake", "http"] = "fake"
    erp_base_url: str = ""
    erp_token: SecretStr = SecretStr("")
    erp_contract_version: Literal["v1"] = "v1"
    erp_connect_timeout_seconds: float = Field(default=3, gt=0)
    erp_read_timeout_seconds: float = Field(default=10, gt=0)
    erp_write_timeout_seconds: float = Field(default=5, gt=0)
    erp_pool_timeout_seconds: float = Field(default=3, gt=0)
    erp_allow_insecure_http: bool = False
    extractor_backend: Literal["disabled", "ollama"] = "disabled"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: float = 120
    ollama_prompt_version: Literal["v1", "v2"] = "v2"
    ollama_think: bool = False
    llm_rollout_mode: Literal["disabled", "shadow", "review"] = "disabled"
    audit_hmac_key: SecretStr = SecretStr("development-only-placeholder")
    llm_max_concurrency: int = Field(default=1, gt=0)
    llm_queue_capacity: int = Field(default=4, ge=0)
    llm_queue_wait_timeout_seconds: float = Field(default=5, gt=0)
    llm_circuit_failure_threshold: int = Field(default=3, gt=0)
    llm_circuit_open_seconds: float = Field(default=30, gt=0)
    llm_circuit_half_open_max_calls: int = Field(default=1, gt=0)
    llm_transport_max_attempts: int = Field(default=1, ge=1)
    readiness_cache_seconds: float = Field(default=5, gt=0)

    @model_validator(mode="after")
    def validate_deployment_configuration(self) -> "Settings":
        if self.persistence_backend == "sqlalchemy" and not self.database_url:
            raise ValueError(
                "database_url is required for sqlalchemy persistence."
            )
        if self.erp_backend == "http":
            self._validate_http_erp()
        active_rollout = self.llm_rollout_mode in {"shadow", "review"}
        if active_rollout and self.extractor_backend != "ollama":
            raise ValueError(
                "shadow/review rollout requires extractor_backend=ollama."
            )
        key = self.audit_hmac_key.get_secret_value().strip()
        placeholders = {
            "",
            "changeme",
            "development-only-placeholder",
            "placeholder",
            "replace-with-a-random-local-secret",
            "replace-with-a-random-secret",
        }
        if active_rollout and key.casefold() in placeholders:
            raise ValueError("Active rollout requires a real audit HMAC key.")
        if self.environment == "production" and (
            key.casefold() in placeholders or len(key) < 32
        ):
            raise ValueError(
                "Production environment requires a non-placeholder audit HMAC "
                "key of at least 32 characters."
            )
        return self

    def _validate_http_erp(self) -> None:
        if not self.erp_token.get_secret_value().strip():
            raise ValueError("erp_token is required for HTTP ERP backend.")
        parsed = urlparse(self.erp_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "erp_base_url must be an absolute HTTP(S) URL for HTTP ERP."
            )
        if parsed.scheme != "http":
            return
        local_hosts = {"localhost", "127.0.0.1", "::1", "erp-stub"}
        if not self.erp_allow_insecure_http or parsed.hostname not in local_hosts:
            raise ValueError(
                "Plain HTTP ERP is allowed only for an explicit local/stub URL "
                "with erp_allow_insecure_http=true."
            )

    model_config = SettingsConfigDict(env_prefix="ORDER_ASSISTANT_")
