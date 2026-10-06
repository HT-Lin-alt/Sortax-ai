from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sortax.infrastructure.persistence.repositories import (
    SQLAlchemyCitationRepository,
    SQLAlchemyConversationRepository,
    SQLAlchemyGenerationRunRepository,
    SQLAlchemyMessageRepository,
    SQLAlchemyRetrievalRunRepository,
)


class PersistenceUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "PersistenceUnitOfWork":
        self._session = self._session_factory()
        self.conversations = SQLAlchemyConversationRepository(self._session)
        self.messages = SQLAlchemyMessageRepository(self._session)
        self.retrieval_runs = SQLAlchemyRetrievalRunRepository(self._session)
        self.generation_runs = SQLAlchemyGenerationRunRepository(self._session)
        self.citations = SQLAlchemyCitationRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()
        self._session = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.rollback()
