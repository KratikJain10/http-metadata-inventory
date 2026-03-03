"""
API routes for the HTTP Metadata Inventory Service.

Provides two endpoints:
- POST /metadata : Synchronously collect and store metadata for a URL.
- GET  /metadata : Retrieve stored metadata, or trigger background collection.
"""

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.models.schemas import (
    AcceptedResponse,
    ErrorResponse,
    MetadataRequest,
    MetadataResponse,
)
from app.repositories.metadata_repo import MetadataRepository
from app.services.background import BackgroundTaskManager
from app.services.collector import CollectionError, collect_metadata

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metadata"])

# These are initialised by the app lifespan and injected here
_repository: MetadataRepository | None = None
_task_manager: BackgroundTaskManager | None = None


def init_routes(
    repository: MetadataRepository,
    task_manager: BackgroundTaskManager,
) -> None:
    """
    Inject dependencies into the route module.

    Called once during application startup from the lifespan handler.
    """
    global _repository, _task_manager
    _repository = repository
    _task_manager = task_manager


def _get_repo() -> MetadataRepository:
    if _repository is None:
        raise RuntimeError("Repository not initialised.")
    return _repository


def _get_task_manager() -> BackgroundTaskManager:
    if _task_manager is None:
        raise RuntimeError("BackgroundTaskManager not initialised.")
    return _task_manager


# ── POST /metadata ──────────────────────────────────────────────────────────


@router.post(
    "/metadata",
    response_model=MetadataResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid URL format."},
        502: {"model": ErrorResponse, "description": "Failed to fetch the URL."},
    },
    summary="Collect metadata for a URL",
    description=(
        "Fetches the HTTP headers, cookies, and page source for the given URL "
        "and stores the result in the database. If metadata for this URL "
        "already exists, it is replaced with freshly collected data."
    ),
)
async def create_metadata(request: MetadataRequest) -> MetadataResponse:
    """
    Synchronously collect and store metadata for a given URL.

    1. Fetch the URL's headers, cookies, and page source.
    2. Store (or replace) the collected data in MongoDB.
    3. Return the full metadata record.
    """
    url = str(request.url)
    repo = _get_repo()

    try:
        document = await collect_metadata(url)
    except CollectionError as exc:
        logger.error("Collection failed for POST %s: %s", url, exc.reason)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to collect metadata: {exc.reason}",
        )

    await repo.upsert_metadata(document)
    logger.info("POST /metadata — stored metadata for %s", url)

    return MetadataResponse(
        url=document.url,
        headers=document.headers,
        cookies=document.cookies,
        page_source=document.page_source,
        collected_at=document.collected_at,
    )


# ── GET /metadata ───────────────────────────────────────────────────────────


@router.get(
    "/metadata",
    response_model=MetadataResponse,
    responses={
        200: {"model": MetadataResponse, "description": "Metadata found and returned."},
        202: {"model": AcceptedResponse, "description": "Metadata not found; collection scheduled."},
        422: {"model": ErrorResponse, "description": "Invalid URL format."},
    },
    summary="Retrieve metadata for a URL",
    description=(
        "Checks the database for existing metadata for the given URL. "
        "If found, returns the full dataset immediately. If not found, "
        "returns a 202 Accepted response and schedules background collection."
    ),
)
async def get_metadata(
    url: str = Query(
        ...,
        description="The URL to retrieve metadata for.",
        examples=["https://example.com"],
    ),
) -> MetadataResponse | AcceptedResponse:
    """
    Retrieve metadata for a URL, or schedule background collection.

    Workflow:
    1. Check if metadata exists in the database.
    2. If found → return 200 with the full dataset.
    3. If not found → return 202 Accepted and trigger an async
       background task to collect and store the metadata.
    """
    # Validate URL format before proceeding
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid URL: '{url}'. URL must start with http:// or https://.",
        )

    repo = _get_repo()
    task_manager = _get_task_manager()

    # Inventory check
    document = await repo.find_by_url(url)

    if document is not None:
        # Immediate resolution — cache hit
        logger.info("GET /metadata — cache hit for %s", url)
        return MetadataResponse(
            url=document.url,
            headers=document.headers,
            cookies=document.cookies,
            page_source=document.page_source,
            collected_at=document.collected_at,
        )

    # Conditional inventory update — cache miss
    # Schedule background collection without blocking the response
    task_manager.schedule_collection(url)
    logger.info("GET /metadata — cache miss for %s, scheduled background collection", url)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=AcceptedResponse(url=url).model_dump(),
    )
