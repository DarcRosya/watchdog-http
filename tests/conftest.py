import asyncio
import os
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from faker import Faker
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.database import Base
from src.core.settings import DatabaseSettings
from src.main import app
from src.models.monitor import Monitor
from src.models.user import User
from src.utils.random_generate import generate_api_key

_UNSET = object()
fake = Faker("en_US")

# =====================================================
# DATABASE FIXTURES
# =====================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create test database engine (session-scoped, tables created once)."""
    test_db_settings = DatabaseSettings(
        USER=os.getenv("DB__USER", "postgres"),
        PASS=SecretStr(os.getenv("DB__PASS", "postgres")),
        HOST=os.getenv("DB__HOST", "localhost"),
        PORT=int(os.getenv("DB__PORT", "5432")),
        NAME=os.getenv("DB__NAME", "watchdog_test"),
    )

    engine = create_async_engine(
        url=test_db_settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create isolated database session per test."""
    connection = await db_engine.connect()
    transaction = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


# =====================================================
# REDIS FIXTURES
# =====================================================


@pytest.fixture(scope="session")
async def redis_client() -> AsyncGenerator[aioredis.Redis, None]:
    """Create Redis connection for tests (session-scoped).

    Tries a real Redis first; falls back to fakeredis (in-memory) if
    available; otherwise skips all Redis-dependent tests.
    """
    redis_host = os.getenv("REDIS__HOST", "localhost")
    redis_port = int(os.getenv("REDIS__PORT", "6379"))

    client = aioredis.Redis(
        host=redis_host,
        port=redis_port,
        db=15,
        decode_responses=True,
    )

    try:
        await client.ping()
    except Exception:
        # Real Redis not available — try fakeredis
        try:
            from fakeredis.asyncio import FakeRedis  # type: ignore

            client = FakeRedis(db=15, decode_responses=True)
            await client.ping()
        except Exception:
            pytest.skip(
                "Redis not available and fakeredis is not installed; "
                "skipping Redis-dependent tests"
            )

    yield client

    try:
        await client.flushdb()
    except Exception:
        pass
    try:
        await client.aclose()
    except Exception:
        pass


@pytest.fixture
async def clean_redis(redis_client: aioredis.Redis) -> None:
    """Clear Redis before each test."""
    await redis_client.flushdb()


# =====================================================
# APPLICATION & CLIENT FIXTURES
# =====================================================


@pytest.fixture
async def client(
    db_session: AsyncSession, redis_client: aioredis.Redis
) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP test client with both DB and Redis overridden."""
    from src.api.dependencies import get_redis
    from src.core.database import get_async_session

    async def override_get_db():
        yield db_session

    app.state.redis = redis_client

    async def override_get_redis():
        return redis_client

    app.dependency_overrides[get_async_session] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =====================================================
# FACTORY FIXTURES
# =====================================================


@pytest.fixture
async def create_user(db_session: AsyncSession):
    """Factory for creating test users."""

    async def _create_user(
        username: str | None = None,
        api_key: str | None = None,
        telegram_chat_id: int | None = _UNSET,
    ) -> User:
        if telegram_chat_id is _UNSET:
            telegram_chat_id = fake.random_int(min=100000, max=999999)

        user = User(
            username=username or fake.user_name(),
            api_key=api_key or generate_api_key(),
            telegram_chat_id=telegram_chat_id,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _create_user


@pytest.fixture
async def create_monitor(db_session: AsyncSession):
    """Factory for creating test monitors."""

    async def _create_monitor(
        user_id: int,
        name: str | None = None,
        url: str | None = None,
        method: str = "GET",
        interval: int = 60,
        is_active: bool = True,
        headers: dict | None = None,
        body: str | None = None,
    ) -> Monitor:
        monitor = Monitor(
            user_id=user_id,
            name=name or fake.sentence(nb_words=3),
            url=url or fake.url(),
            method=method,
            interval=interval,
            is_active=is_active,
            headers=headers,
            body=body,
        )
        db_session.add(monitor)
        await db_session.commit()
        await db_session.refresh(monitor)
        return monitor

    return _create_monitor


# =====================================================
# SAMPLE DATA FIXTURES
# =====================================================


@pytest.fixture
async def sample_user(create_user) -> User:
    """Create sample test user with a fixed, known API key."""
    return await create_user(
        username="test_user",
        api_key="test-api-key-1234567890abcdef1234567890abcdef1234567890abcdef12",
    )


@pytest.fixture
async def sample_monitors(sample_user: User, create_monitor) -> list[Monitor]:
    """Create a set of pre-built monitors for the sample user."""
    urls = [
        "https://httpbin.org/status/200",
        "https://example.com",
        "https://jsonplaceholder.typicode.com/posts",
    ]
    return [
        await create_monitor(
            user_id=sample_user.id, url=url, name=f"Monitor for {url}", interval=60
        )
        for url in urls
    ]


# =====================================================
# UTILITY FIXTURES
# =====================================================


@pytest.fixture
def auth_headers(sample_user: User) -> dict:
    """Return auth headers with API key."""
    return {"X-API-Key": sample_user.api_key}


@pytest.fixture
def mock_redis():
    """Mock Redis client for unit tests."""
    return AsyncMock(spec=aioredis.Redis)
