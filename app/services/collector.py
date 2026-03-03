"""
HTTP metadata collector service.

Responsible for fetching a URL and extracting its response headers,
cookies, and page source (HTML body). Uses httpx for async HTTP
requests. JavaScript execution is out of scope — only static content
is retrieved.
"""

import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models.schemas import MetadataDocument

logger = logging.getLogger(__name__)


class CollectionError(Exception):
    """Raised when metadata collection fails for a URL."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Failed to collect metadata for {url}: {reason}")


async def collect_metadata(url: str) -> MetadataDocument:
    """
    Fetch a URL and extract its HTTP metadata.

    Args:
        url: The target URL to collect metadata from.

    Returns:
        A MetadataDocument containing headers, cookies, and page source.

    Raises:
        CollectionError: If the request fails due to timeout,
            connection error, or any other HTTP issue.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.REQUEST_TIMEOUT),
            follow_redirects=True,
        ) as client:
            response = await client.get(url)

            # Extract headers as a flat dict (lowercase keys)
            headers = dict(response.headers)

            # Extract cookies as a flat dict
            cookies = {
                name: value
                for name, value in response.cookies.items()
            }

            # Page source is the full response body text
            page_source = response.text

            document = MetadataDocument(
                url=url,
                headers=headers,
                cookies=cookies,
                page_source=page_source,
                collected_at=datetime.now(timezone.utc),
            )

            logger.info(
                "Collected metadata for %s (status=%d, size=%d bytes)",
                url,
                response.status_code,
                len(page_source),
            )
            return document

    except httpx.TimeoutException as exc:
        logger.error("Timeout while fetching %s: %s", url, exc)
        raise CollectionError(url, f"Request timed out after {settings.REQUEST_TIMEOUT}s") from exc

    except httpx.ConnectError as exc:
        logger.error("Connection error for %s: %s", url, exc)
        raise CollectionError(url, f"Could not connect to host: {exc}") from exc

    except httpx.InvalidURL as exc:
        logger.error("Invalid URL: %s — %s", url, exc)
        raise CollectionError(url, f"Invalid URL format: {exc}") from exc

    except httpx.HTTPError as exc:
        logger.error("HTTP error for %s: %s", url, exc)
        raise CollectionError(url, f"HTTP error: {exc}") from exc
