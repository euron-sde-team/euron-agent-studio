"""Runtime configuration, validated once at boot.

Every setting comes from the environment. `get_settings()` is cached, so the whole process
shares one frozen `Settings`. In production, `production_problems()` refuses development
defaults and reports every problem at once instead of one per restart.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Shipped so `uvicorn` starts with zero configuration on a laptop. Production refuses it.
DEV_SECRET = "dev-only-insecure-secret-do-not-use-in-production"  # noqa: S105
# A valid 32-byte key derived from the development secret, refused in production as well.
DEV_ENCRYPTION_KEY = base64.b64encode(hashlib.sha256(DEV_SECRET.encode()).digest()).decode()

AppEnv = Literal["development", "test", "production"]
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    app_env: AppEnv = "development"
    product_name: str = "Euron AgentStudio"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["json", "console"] = "json"

    # HTTP
    cors_origins: CsvList = Field(
        default_factory=lambda: ["http://localhost:3120", "http://127.0.0.1:3120"]
    )
    web_url: str = "http://localhost:3120"
    # Where integrators reach the API: webhook URLs and exported scripts are built from it.
    public_api_url: str = "http://localhost:8120"

    # Postgres
    database_url: str = "postgresql+asyncpg://agentstudio:agentstudio@localhost:5452/agentstudio"
    # AWS: the RDS-managed secret holding the password; read per new connection.
    database_secret_arn: str | None = None
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_echo: bool = False
    migrate_on_boot: bool = False

    # Redis: run trace streams, rate limits, session revocation, caches
    redis_url: str = "redis://localhost:6412/0"

    # Sessions, API keys and encryption at rest
    session_secret: SecretStr = SecretStr(DEV_SECRET)
    session_ttl_hours: int = Field(default=168, ge=1, le=2160)
    api_key_pepper: SecretStr = SecretStr(DEV_SECRET)
    # Base64 of 32 random bytes: encrypts workspace secrets and webhook signing keys.
    encryption_key: SecretStr = SecretStr(DEV_ENCRYPTION_KEY)
    cookie_secure: bool = False
    cookie_domain: str | None = None
    allow_signup: bool = False

    # Knowledge documents (original files)
    storage_backend: Literal["s3", "local"] = "local"
    storage_dir: Path = Path("data/files")
    s3_bucket: str | None = None
    s3_kms_key_id: str | None = None
    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    max_document_kb: int = Field(default=2048, ge=1, le=20480)

    # Run queue and worker
    queue_backend: Literal["sqs", "inline"] = "inline"
    sqs_queue_url: str | None = None
    worker_concurrency: int = Field(default=4, ge=1, le=64)
    worker_shutdown_grace_s: int = Field(default=60, ge=1, le=3600)
    heartbeat_s: int = Field(default=15, ge=1, le=300)
    stale_run_s: int = Field(default=90, ge=10, le=3600)

    # Engine guard rails
    run_timeout_s: int = Field(default=900, ge=10, le=86400)
    max_parallel_steps: int = Field(default=4, ge=1, le=32)
    max_nodes: int = Field(default=200, ge=2, le=2000)
    max_edges: int = Field(default=400, ge=1, le=4000)
    max_graph_kb: int = Field(default=512, ge=16, le=8192)
    max_loop_items: int = Field(default=200, ge=1, le=10000)
    max_agent_iterations: int = Field(default=10, ge=1, le=50)
    max_step_payload_kb: int = Field(default=256, ge=8, le=8192)
    max_active_runs_per_workspace: int = Field(default=20, ge=1, le=10000)
    max_run_wait_s: int = Field(default=30, ge=0, le=120)

    # HTTP request node
    http_allowed_hosts: CsvList = Field(default_factory=list)
    http_allow_private_networks: bool = False
    http_max_response_kb: int = Field(default=1024, ge=1, le=65536)

    # Model providers. The offline provider is always available.
    default_model: str = "offline"
    openai_base_url: str | None = None
    openai_api_key: SecretStr | None = None
    openai_models: CsvList = Field(default_factory=lambda: ["gpt-4o-mini", "gpt-4.1-mini"])
    ollama_url: str | None = None
    ollama_models: CsvList = Field(default_factory=lambda: ["llama3.2", "qwen3:4b"])
    # JSON object: {"model": [input USD per 1M tokens, output USD per 1M tokens]}
    model_prices: str = ""
    llm_timeout_s: float = Field(default=120.0, gt=0, le=1800)
    # Simulated list price for the offline provider, so cost tracking has something to show.
    offline_price_input: float = Field(default=0.15, ge=0)
    offline_price_output: float = Field(default=0.60, ge=0)
    # A delay proportional to output length makes live traces visible in demos. Zero in tests.
    offline_delay_ms_per_100_tokens: int = Field(default=0, ge=0, le=10000)

    # Rate limits, requests per minute
    rate_limit_login: int = Field(default=10, ge=1)
    rate_limit_runs: int = Field(default=60, ge=1)
    rate_limit_webhooks: int = Field(default=120, ge=1)
    rate_limit_offline: int = Field(default=600, ge=1)
    rate_limit_upload: int = Field(default=60, ge=1)

    webhook_tolerance_s: int = Field(default=300, ge=30, le=3600)
    demo_password: SecretStr | None = None

    @field_validator(
        "cors_origins", "http_allowed_hosts", "openai_models", "ollama_models", mode="before"
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def max_document_bytes(self) -> int:
        return self.max_document_kb * 1024

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_base_url)

    @property
    def ollama_enabled(self) -> bool:
        return bool(self.ollama_url)

    def production_problems(self) -> list[str]:
        """Every reason this configuration is unsafe to serve real users."""
        problems: list[str] = []
        session = self.session_secret.get_secret_value()
        pepper = self.api_key_pepper.get_secret_value()
        for name, value in (("SESSION_SECRET", session), ("API_KEY_PEPPER", pepper)):
            if value == DEV_SECRET or len(value) < 32:
                problems.append(f"{name} must be a random value of at least 32 characters")
        if session == pepper:
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        key = self.encryption_key.get_secret_value()
        if key == DEV_ENCRYPTION_KEY or not _is_key(key):
            problems.append("ENCRYPTION_KEY must be the base64 encoding of 32 random bytes")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true behind HTTPS")
        if not self.cors_origins or "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list the web app origins explicitly")
        if self.storage_backend != "s3" or not self.s3_bucket:
            problems.append("STORAGE_BACKEND=s3 with S3_BUCKET is required")
        if self.queue_backend != "sqs" or not self.sqs_queue_url:
            problems.append("QUEUE_BACKEND=sqs with SQS_QUEUE_URL is required")
        if self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL points at an emulator; unset it in production")
        if self.http_allow_private_networks:
            problems.append(
                "HTTP_ALLOW_PRIVATE_NETWORKS lets flows reach internal services; "
                "list the hosts in HTTP_ALLOWED_HOSTS instead"
            )
        return problems


def _is_key(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except ValueError:
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
