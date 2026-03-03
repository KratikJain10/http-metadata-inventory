"""
MongoDB repository for metadata documents.

Encapsulates all database operations, providing a clean interface
between the service layer and the database. Uses the indexed `url`
field for all lookups.
"""

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_database
from app.models.schemas import MetadataDocument

logger = logging.getLogger(__name__)


class MetadataRepository:
    """Data access layer for the metadata collection in MongoDB."""

    COLLECTION_NAME = "metadata"

    def __init__(self, database: AsyncIOMotorDatabase | None = None) -> None:
        """
        Initialise with an optional database instance.

        If none is provided, the global database connection is used.
        This allows injecting a test database during testing.
        """
        self._db = database

    @property
    def _collection(self):
        """Lazy access to the metadata collection."""
        db = self._db or get_database()
        return db[self.COLLECTION_NAME]

    async def find_by_url(self, url: str) -> MetadataDocument | None:
        """
        Look up a metadata record by its URL.

        Returns None if the URL has no stored metadata.
        """
        document = await self._collection.find_one({"url": url})
        if document is None:
            return None
        return MetadataDocument.from_mongo_dict(document)

    async def upsert_metadata(self, metadata: MetadataDocument) -> None:
        """
        Insert or update a metadata record.

        Uses the `url` field as the unique key. If a record for this URL
        already exists, it will be completely replaced with the new data.
        """
        data = metadata.to_mongo_dict()
        await self._collection.replace_one(
            {"url": metadata.url},
            data,
            upsert=True,
        )
        logger.info("Upserted metadata for URL: %s", metadata.url)

    async def delete_by_url(self, url: str) -> bool:
        """
        Delete a metadata record by URL.

        Returns True if a document was deleted, False otherwise.
        Primarily used for testing and cleanup.
        """
        result = await self._collection.delete_one({"url": url})
        return result.deleted_count > 0

    async def count(self) -> int:
        """Return the total number of metadata records."""
        return await self._collection.count_documents({})
