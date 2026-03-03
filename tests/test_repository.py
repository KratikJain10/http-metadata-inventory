"""
Unit tests for the MetadataRepository (MongoDB data access layer).

Uses mongomock-motor (via conftest fixtures) to run against an
in-memory MongoDB without requiring a real database instance.
"""

import pytest

from app.models.schemas import MetadataDocument


@pytest.mark.asyncio
class TestMetadataRepository:
    """Tests for MetadataRepository CRUD operations."""

    async def test_upsert_and_find(self, repository, sample_metadata):
        """Verify a document can be inserted and retrieved by URL."""
        await repository.upsert_metadata(sample_metadata)

        result = await repository.find_by_url(sample_metadata.url)

        assert result is not None
        assert result.url == sample_metadata.url
        assert result.headers == sample_metadata.headers
        assert result.cookies == sample_metadata.cookies
        assert result.page_source == sample_metadata.page_source

    async def test_find_nonexistent_returns_none(self, repository):
        """Verify querying a missing URL returns None."""
        result = await repository.find_by_url("https://nonexistent.example.com")
        assert result is None

    async def test_upsert_replaces_existing(self, repository, sample_metadata):
        """Verify upserting the same URL replaces the old record."""
        await repository.upsert_metadata(sample_metadata)

        # Update with new data
        updated = MetadataDocument(
            url=sample_metadata.url,
            headers={"x-new": "header"},
            cookies={},
            page_source="<html>Updated</html>",
        )
        await repository.upsert_metadata(updated)

        result = await repository.find_by_url(sample_metadata.url)
        assert result is not None
        assert result.headers == {"x-new": "header"}
        assert result.page_source == "<html>Updated</html>"

        # Only one document should exist
        count = await repository.count()
        assert count == 1

    async def test_delete_by_url(self, repository, sample_metadata):
        """Verify a document can be deleted by URL."""
        await repository.upsert_metadata(sample_metadata)

        deleted = await repository.delete_by_url(sample_metadata.url)
        assert deleted is True

        result = await repository.find_by_url(sample_metadata.url)
        assert result is None

    async def test_delete_nonexistent_returns_false(self, repository):
        """Verify deleting a non-existent URL returns False."""
        deleted = await repository.delete_by_url("https://ghost.example.com")
        assert deleted is False

    async def test_count(self, repository, sample_metadata):
        """Verify document count is accurate."""
        assert await repository.count() == 0

        await repository.upsert_metadata(sample_metadata)
        assert await repository.count() == 1

        # Upsert same URL should not increase count
        await repository.upsert_metadata(sample_metadata)
        assert await repository.count() == 1

        # Add a different URL
        other = MetadataDocument(
            url="https://other.example.com",
            headers={},
            cookies={},
            page_source="",
        )
        await repository.upsert_metadata(other)
        assert await repository.count() == 2
