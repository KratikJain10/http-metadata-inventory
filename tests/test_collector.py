"""
Unit tests for the HTTP metadata collector service.

Tests use respx to mock HTTP responses so no real network calls are made.
"""

import pytest
import respx
from httpx import Response

from app.services.collector import CollectionError, collect_metadata


@pytest.mark.asyncio
class TestCollectMetadata:
    """Tests for the collect_metadata function."""

    @respx.mock
    async def test_successful_collection(self):
        """Verify metadata is correctly extracted from a successful response."""
        url = "https://example.com"
        html = "<html><head><title>Test</title></head><body>Hello</body></html>"

        respx.get(url).mock(
            return_value=Response(
                200,
                text=html,
                headers={"content-type": "text/html", "x-custom": "value"},
            )
        )

        result = await collect_metadata(url)

        assert result.url == url
        assert result.page_source == html
        assert "content-type" in result.headers
        assert result.headers["x-custom"] == "value"
        assert result.collected_at is not None

    @respx.mock
    async def test_collection_extracts_cookies(self):
        """Verify cookies are extracted from the response."""
        url = "https://example.com"

        respx.get(url).mock(
            return_value=Response(
                200,
                text="<html></html>",
                headers={
                    "content-type": "text/html",
                    "set-cookie": "session=abc123; Path=/",
                },
            )
        )

        result = await collect_metadata(url)

        assert result.url == url
        assert isinstance(result.cookies, dict)

    @respx.mock
    async def test_collection_follows_redirects(self):
        """Verify redirects are followed and final content is captured."""
        url = "https://redirect-source.example.com"
        final_url = "https://redirect-target.example.com/final"
        final_html = "<html><body>Final</body></html>"

        respx.get(url).mock(
            return_value=Response(
                301,
                headers={"location": final_url},
            )
        )
        respx.get(final_url).mock(
            return_value=Response(200, text=final_html)
        )

        result = await collect_metadata(url)
        assert result.page_source == final_html

    @respx.mock
    async def test_timeout_raises_collection_error(self):
        """Verify a timeout produces a CollectionError."""
        import httpx

        url = "https://slow-site.example.com"
        respx.get(url).mock(side_effect=httpx.TimeoutException("timed out"))

        with pytest.raises(CollectionError) as exc_info:
            await collect_metadata(url)

        assert "timed out" in str(exc_info.value)
        assert exc_info.value.url == url

    @respx.mock
    async def test_connection_error_raises_collection_error(self):
        """Verify a connection failure produces a CollectionError."""
        import httpx

        url = "https://unreachable.example.com"
        respx.get(url).mock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(CollectionError) as exc_info:
            await collect_metadata(url)

        assert exc_info.value.url == url

    @respx.mock
    async def test_large_page_source(self):
        """Verify large HTML content is handled correctly."""
        url = "https://example.com"
        large_html = "<html>" + "x" * 100_000 + "</html>"

        respx.get(url).mock(return_value=Response(200, text=large_html))

        result = await collect_metadata(url)
        assert len(result.page_source) == len(large_html)
