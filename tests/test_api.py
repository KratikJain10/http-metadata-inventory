"""
Integration tests for the API endpoints.

Tests the full request → route → service → repository flow using
the FastAPI test client with a mock MongoDB backend.
"""

import asyncio
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from app.models.schemas import MetadataDocument


@pytest.mark.asyncio
class TestPostMetadata:
    """Tests for POST /metadata endpoint."""

    @respx.mock
    async def test_post_valid_url_returns_201(self, test_client):
        """POST with a valid URL should collect metadata and return 201."""
        url = "https://httpbin.org/html"
        html = "<html><body><h1>Hello</h1></body></html>"

        respx.get(url).mock(
            return_value=Response(
                200,
                text=html,
                headers={"content-type": "text/html"},
            )
        )

        response = await test_client.post(
            "/metadata",
            json={"url": url},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["url"] == url
        assert data["page_source"] == html
        assert "headers" in data
        assert "cookies" in data
        assert "collected_at" in data

    async def test_post_invalid_url_returns_422(self, test_client):
        """POST with an invalid URL should return 422 validation error."""
        response = await test_client.post(
            "/metadata",
            json={"url": "not-a-valid-url"},
        )
        assert response.status_code == 422

    async def test_post_missing_url_returns_422(self, test_client):
        """POST with no body should return 422."""
        response = await test_client.post("/metadata", json={})
        assert response.status_code == 422

    @respx.mock
    async def test_post_unreachable_url_returns_502(self, test_client):
        """POST with an unreachable URL should return 502."""
        import httpx

        url = "https://unreachable.example.com"
        respx.get(url).mock(side_effect=httpx.ConnectError("connection refused"))

        response = await test_client.post(
            "/metadata",
            json={"url": url},
        )

        assert response.status_code == 502
        assert "Failed to collect metadata" in response.json()["detail"]


@pytest.mark.asyncio
class TestGetMetadata:
    """Tests for GET /metadata endpoint."""

    async def test_get_existing_url_returns_200(self, test_client, repository):
        """GET for a URL with stored metadata should return 200."""
        url = "https://example.com"
        html = "<html><body>Example</body></html>"

        # Seed the database directly via the repository
        doc = MetadataDocument(
            url=url,
            headers={"content-type": "text/html"},
            cookies={},
            page_source=html,
            collected_at=datetime.now(timezone.utc),
        )
        await repository.upsert_metadata(doc)

        # GET should return the stored data
        response = await test_client.get("/metadata", params={"url": url})

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == url
        assert data["page_source"] == html

    async def test_get_missing_url_returns_202(self, test_client):
        """GET for an uncached URL should return 202 Accepted."""
        url = "https://never-seen-before.example.com"

        response = await test_client.get("/metadata", params={"url": url})

        assert response.status_code == 202
        data = response.json()
        assert data["url"] == url
        assert data["status"] == "pending"
        assert "scheduled" in data["message"].lower() or "accepted" in data["message"].lower()

    async def test_get_missing_url_param_returns_422(self, test_client):
        """GET without a url query parameter should return 422."""
        response = await test_client.get("/metadata")
        assert response.status_code == 422

    @respx.mock
    async def test_get_after_background_collection_returns_200(self, test_client):
        """
        GET for a missing URL triggers background collection.
        After the background task completes, a second GET should return 200.
        """
        url = "https://delayed.example.com"
        html = "<html><body>Delayed Content</body></html>"

        # Mock the URL that the background worker will fetch
        respx.get(url).mock(
            return_value=Response(
                200,
                text=html,
                headers={"content-type": "text/html"},
            )
        )

        # First GET — should be a cache miss → 202
        response = await test_client.get("/metadata", params={"url": url})
        assert response.status_code == 202

        # Wait for the background task to complete
        await asyncio.sleep(1.0)

        # Second GET — should now be a cache hit → 200
        response = await test_client.get("/metadata", params={"url": url})
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == url
        assert data["page_source"] == html


@pytest.mark.asyncio
class TestHealthCheck:
    """Tests for the health check endpoint."""

    async def test_health_returns_200(self, test_client):
        """Health endpoint should always return 200."""
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
