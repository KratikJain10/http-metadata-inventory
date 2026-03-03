"""
MongoDB connection manager with retry logic and index creation.

Provides async connection lifecycle management using motor,
with exponential backoff retries for resilience during startup.
"""

import asyncio
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level references managed by lifespan
_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None


async def connect_to_mongodb(
    max_retries: int = 5,
    base_delay: float = 1.0,
) -> None:
    """
    Establish a connection to MongoDB with exponential backoff retries.

    This ensures the API remains resilient if MongoDB takes a few seconds
    to become available (e.g., during docker-compose startup).
    """
    global _client, _database

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Connecting to MongoDB (attempt %d/%d)...", attempt, max_retries
            )
            _client = AsyncIOMotorClient(
                settings.MONGO_URI,
                serverSelectionTimeoutMS=5000,
            )
            # Force a connection check
            await _client.admin.command("ping")
            _database = _client[settings.MONGO_DB_NAME]

            # Create indexes for fast URL lookups
            await _database.metadata.create_index("url", unique=True)

            logger.info("Connected to MongoDB successfully.")
            return

        except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
            if attempt == max_retries:
                logger.error("Failed to connect to MongoDB after %d attempts.", max_retries)
                raise exc

            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "MongoDB not ready, retrying in %.1fs... (%s)", delay, exc
            )
            await asyncio.sleep(delay)


async def close_mongodb_connection() -> None:
    """Close the MongoDB client connection gracefully."""
    global _client, _database
    if _client is not None:
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed.")


def get_database() -> AsyncIOMotorDatabase:
    """
    Return the active database instance.

    Raises RuntimeError if called before connection is established.
    """
    if _database is None:
        raise RuntimeError(
            "Database is not initialised. Ensure connect_to_mongodb() "
            "has been called during application startup."
        )
    return _database
