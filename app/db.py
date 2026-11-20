from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings


def make_engine(settings: Settings, *, migration: bool = False):
    url = (settings.migration_database_url or settings.database_url) if migration else settings.database_url
    return create_async_engine(
        url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "command_timeout": None if migration else settings.db_command_timeout_seconds,
        },
        pool_pre_ping=True,
        hide_parameters=True,
    )


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session:
        yield session
