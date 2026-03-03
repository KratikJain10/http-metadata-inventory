"""
Shared test fixtures for the metadata inventory service test suite.

Provides:
- Async event loop configuration
- Test MongoDB database (mongomock-motor for unit tests)
- Repository and task manager instances
- FastAPI test client
"""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.models.schemas import MetadataDocument
from app.repositories.metadata_repo import MetadataRepository
from app.services.background import BackgroundTaskManager


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_db():
    """
    Provide a mock MongoDB database using mongomock-motor.

    This avoids the need for a running MongoDB instance during unit tests.
    Each test gets a fresh database to prevent cross-test contamination.
    """
    client = AsyncMongoMockClient()
    db = client["test_metadata_inventory"]
    # Create the same index as production
    await db.metadata.create_index("url", unique=True)
    yield db
    client.close()


@pytest_asyncio.fixture
async def repository(mock_db) -> MetadataRepository:
    """Provide a MetadataRepository backed by the mock database."""
    return MetadataRepository(database=mock_db)


@pytest_asyncio.fixture
async def task_manager(repository) -> BackgroundTaskManager:
    """Provide a BackgroundTaskManager with the test repository."""
    manager = BackgroundTaskManager(repository=repository)
    yield manager
    await manager.cancel_all()


@pytest_asyncio.fixture
async def test_client(mock_db, repository, task_manager) -> AsyncGenerator:
    """
    Provide an async HTTP test client for the FastAPI application.

    Injects the test database, repository, and task manager to avoid
    connecting to a real MongoDB instance.
    """
    from app.routes.metadata import init_routes, router
    from app.main import app

    # Inject test dependencies into routes
    init_routes(repository=repository, task_manager=task_manager)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def sample_metadata() -> MetadataDocument:
    """Provide a sample MetadataDocument for testing."""
    from datetime import datetime, timezone

    return MetadataDocument(
        url="https://example.com",
        headers={"content-type": "text/html; charset=UTF-8", "server": "ECS"},
        cookies={"session": "abc123"},
        page_source="<!doctype html><html><head><title>Example</title></head></html>",
        collected_at=datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
