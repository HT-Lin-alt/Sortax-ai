import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sortax import __version__
from sortax.api.exception_handlers import register_exception_handlers
from sortax.api.health import router as health_router
from sortax.api.models import ErrorEnvelope, ErrorPayload, HealthStatus
from sortax.chat import CancellationStore, ChatCoordinator, InMemoryCancellationStore
from sortax.chat.router import router as chat_router
from sortax.config import Settings, get_settings
from sortax.embedding_gateway import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from sortax.identity.jwt_service import JwtService
from sortax.identity.router import development_router
from sortax.identity.router import router as identity_router
from sortax.infrastructure.milvus import MilvusVectorStore, VectorStoreUnavailable
from sortax.infrastructure.persistence import Database
from sortax.infrastructure.redis_cancellation import RedisCancellationStore
from sortax.infrastructure.redis_health import RedisHealthProbe
from sortax.intent import FakeIntentClassifier, IntentClassifier
from sortax.llm_gateway import FakeLLMProvider, LLMProvider, OpenAILLMProvider
from sortax.observability.logging import configure_logging
from sortax.observability.middleware import RequestContextMiddleware
from sortax.rag import FakeRetriever, MilvusRetriever, Retriever, VectorStore

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    vector_store: VectorStore | None = None,
    database: Database | None = None,
    redis_probe: RedisHealthProbe | None = None,
    cancellation_store: CancellationStore | None = None,
    retriever: Retriever | None = None,
    intent_classifier: IntentClassifier | None = None,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        app.state.jwt_service = JwtService(app_settings)
        checks: dict[str, str] = {"application": "ok"}
        configured_database = database
        if app_settings.database_enabled:
            configured_database = configured_database or Database(app_settings.database_url)
            database_ready = await configured_database.healthcheck()
            checks["postgresql"] = "ok" if database_ready else "unavailable"

        configured_redis = redis_probe
        if app_settings.redis_enabled:
            configured_redis = configured_redis or RedisHealthProbe(app_settings.redis_url)
            redis_ready = await configured_redis.healthcheck()
            checks["redis"] = "ok" if redis_ready else "unavailable"
        configured_cancellation = cancellation_store
        if configured_cancellation is None:
            configured_cancellation = (
                RedisCancellationStore(
                    app_settings.redis_url,
                    ttl_seconds=app_settings.cancellation_ttl_seconds,
                )
                if app_settings.redis_enabled
                else InMemoryCancellationStore()
            )

        configured_store = vector_store
        if app_settings.milvus_enabled:
            configured_store = configured_store or MilvusVectorStore.from_settings(app_settings)
            try:
                await configured_store.connect()
            except VectorStoreUnavailable:
                logger.error("milvus_unavailable")
                checks["milvus"] = "unavailable"
            else:
                checks["milvus"] = "ok"

        app.state.vector_store = configured_store
        app.state.database = configured_database
        app.state.session_factory = (
            configured_database.session_factory if configured_database is not None else None
        )
        configured_retriever = retriever
        configured_intent_classifier = intent_classifier
        configured_llm = llm_provider
        if app_settings.app_env == "test":
            configured_retriever = configured_retriever or FakeRetriever()
        elif configured_retriever is None and configured_store is not None:
            configured_retriever = MilvusRetriever(
                provider=_embedding_provider(app_settings),
                store=configured_store,
                collection_name=app_settings.milvus_collection,
                top_k=app_settings.retrieval_top_k,
                score_threshold=app_settings.retrieval_score_threshold,
            )
        elif app_settings.app_env == "development":
            configured_retriever = FakeRetriever()
        if app_settings.app_env in {"development", "test"}:
            configured_intent_classifier = configured_intent_classifier or FakeIntentClassifier()
        if configured_llm is None and (
            app_settings.llm_provider == "openai" or app_settings.app_env in {"development", "test"}
        ):
            configured_llm = _llm_provider(app_settings)
        app.state.chat_coordinator = (
            ChatCoordinator(
                configured_database.session_factory,
                intent_classifier=configured_intent_classifier,
                retriever=configured_retriever,
                llm=configured_llm,
                cancellation_store=configured_cancellation,
                first_token_timeout_seconds=app_settings.first_token_timeout_seconds,
                heartbeat_seconds=app_settings.stream_heartbeat_seconds,
                max_duration_seconds=app_settings.stream_max_duration_seconds,
                cancellation_poll_seconds=app_settings.cancellation_poll_seconds,
            )
            if configured_database is not None
            and configured_retriever is not None
            and configured_intent_classifier is not None
            and configured_llm is not None
            else None
        )
        app.state.redis = configured_redis
        app.state.readiness_checks = checks
        app.state.ready = all(result == "ok" for result in checks.values())
        try:
            yield
        finally:
            app.state.ready = False
            if configured_store is not None:
                await configured_store.close()
            if configured_redis is not None:
                await configured_redis.close()
            await configured_cancellation.close()
            if configured_database is not None:
                await configured_database.close()

    app = FastAPI(title="Sortax Chat API", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(identity_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    if app_settings.development_token_enabled:
        app.include_router(development_router, prefix="/api/v1")
    return app


def _embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(
            dimensions=settings.embedding_dimensions,
            model_name=settings.embedding_model,
        )
    api_key = settings.embedding_api_key
    if api_key is None:
        raise ValueError("SORTAX_EMBEDDING_API_KEY is required for the OpenAI provider")
    if settings.embedding_model.startswith("fake-"):
        raise ValueError("a real embedding model is required for the OpenAI provider")
    return OpenAIEmbeddingProvider(
        api_key=api_key.get_secret_value(),
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
    )


def _llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeLLMProvider()
    api_key = settings.llm_api_key
    if api_key is None:
        raise ValueError("SORTAX_LLM_API_KEY is required for the OpenAI provider")
    return OpenAILLMProvider(
        api_key=api_key.get_secret_value(),
        model_name=settings.llm_model,
        request_timeout_seconds=settings.llm_request_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def _missing_configuration_app(_exc: ValidationError) -> FastAPI:
    configure_logging("INFO")
    fallback = FastAPI(title="Sortax Chat API", version=__version__)
    fallback.add_middleware(RequestContextMiddleware)

    @fallback.get("/health/live", tags=["health"])
    async def health_live() -> HealthStatus:
        return HealthStatus(status="ok")

    @fallback.get("/health/ready", tags=["health"])
    async def health_ready(request: Request) -> JSONResponse:
        request_id = str(request.state.request_id)
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="configuration_error",
                message="Application configuration is invalid",
                request_id=request_id,
            )
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=envelope.model_dump(mode="json", exclude_none=True),
            headers={"X-Request-ID": request_id},
        )

    return fallback


try:
    app = create_app()
except ValidationError as configuration_error:  # pragma: no cover - startup safety net
    app = _missing_configuration_app(configuration_error)
