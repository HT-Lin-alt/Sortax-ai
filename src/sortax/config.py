from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SORTAX_",
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_issuer: str = "sortax-dev"
    jwt_audience: str = "sortax-api"
    jwt_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_enabled: bool = True
    database_url: str = "postgresql+asyncpg://sortax:sortax@localhost:5432/sortax"
    redis_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    llm_provider: Literal["fake", "openai"] = "fake"
    llm_model: str = "fake-chat-v1"
    llm_api_key: SecretStr | None = None
    llm_request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    llm_max_output_tokens: int = Field(default=1024, ge=1, le=100_000)
    first_token_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    stream_heartbeat_seconds: float = Field(default=15.0, gt=0, le=60)
    stream_max_duration_seconds: float = Field(default=300.0, gt=0, le=600)
    cancellation_poll_seconds: float = Field(default=0.5, gt=0, le=5)
    cancellation_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    milvus_enabled: bool = True
    milvus_uri: str = "http://localhost:19530"
    milvus_token: SecretStr | None = None
    milvus_database: str = "default"
    milvus_collection: str = "ato_knowledge_demo"
    milvus_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    ato_data_dir: Path = Path("data/ato")
    ato_manifest_path: Path = Path("manifests/ato/sources.yaml")
    embedding_provider: Literal["fake", "openai"] = "fake"
    embedding_model: str = "fake-embedding-v1"
    embedding_dimensions: int = Field(default=64, gt=1, le=65_536)
    embedding_api_key: SecretStr | None = None
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    retrieval_top_k: int = Field(default=5, ge=1, le=50)
    retrieval_score_threshold: float = Field(default=0.15, ge=0, le=1)
    knowledge_max_file_bytes: int = Field(default=10_485_760, ge=1, le=104_857_600)
    knowledge_chunk_size: int = Field(default=1200, ge=200, le=10_000)
    knowledge_chunk_overlap: int = Field(default=200, ge=0, le=2_000)

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "Settings":
        if self.llm_provider == "openai" and self.llm_api_key is None:
            raise ValueError("SORTAX_LLM_API_KEY is required for the OpenAI provider")
        if self.llm_provider == "openai" and self.llm_model.startswith("fake-"):
            raise ValueError("a real LLM model is required for the OpenAI provider")
        if self.first_token_timeout_seconds > self.stream_max_duration_seconds:
            raise ValueError("first-token timeout cannot exceed total stream duration")
        if self.stream_heartbeat_seconds > self.stream_max_duration_seconds:
            raise ValueError("heartbeat interval cannot exceed total stream duration")
        return self

    @property
    def development_token_enabled(self) -> bool:
        return self.app_env in {"development", "test"}


class WorkerSettings(BaseSettings):
    """Worker-only configuration that does not require API authentication settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SORTAX_",
        extra="ignore",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"


class KnowledgeSettings(BaseSettings):
    """Settings needed by the offline ingestion command only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SORTAX_",
        extra="ignore",
    )

    milvus_uri: str = "http://localhost:19530"
    milvus_token: SecretStr | None = None
    milvus_database: str = "default"
    milvus_collection: str = "ato_knowledge_demo"
    milvus_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    ato_data_dir: Path = Path("data/ato")
    ato_manifest_path: Path = Path("manifests/ato/sources.yaml")
    embedding_provider: Literal["fake", "openai"] = "fake"
    embedding_model: str = "fake-embedding-v1"
    embedding_dimensions: int = Field(default=64, gt=1, le=65_536)
    embedding_api_key: SecretStr | None = None
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    knowledge_max_file_bytes: int = Field(default=10_485_760, ge=1, le=104_857_600)
    knowledge_chunk_size: int = Field(default=1200, ge=200, le=10_000)
    knowledge_chunk_overlap: int = Field(default=200, ge=0, le=2_000)

    @model_validator(mode="after")
    def validate_ingestion_settings(self) -> "KnowledgeSettings":
        if self.knowledge_chunk_overlap >= self.knowledge_chunk_size:
            raise ValueError("knowledge chunk overlap must be smaller than chunk size")
        if self.embedding_provider == "openai" and self.embedding_api_key is None:
            raise ValueError("SORTAX_EMBEDDING_API_KEY is required for the OpenAI provider")
        if self.embedding_provider == "openai" and self.embedding_model.startswith("fake-"):
            raise ValueError("a real embedding model is required for the OpenAI provider")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
