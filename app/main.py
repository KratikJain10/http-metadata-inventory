"""
FastAPI application factory with lifespan management.

Handles:
- MongoDB connection lifecycle (connect on startup, close on shutdown)
- Background task manager initialisation and cleanup
- Global exception handling
- Router registration
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import close_mongodb_connection, connect_to_mongodb
from app.repositories.metadata_repo import MetadataRepository
from app.routes.metadata import init_routes, router as metadata_router
from app.services.background import BackgroundTaskManager

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Module-level reference for shutdown access
_task_manager: BackgroundTaskManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup:
      1. Connect to MongoDB (with retry logic for Docker startup delays).
      2. Initialise the repository and background task manager.
      3. Inject dependencies into the route module.

    Shutdown:
      1. Cancel all in-flight background tasks.
      2. Close the MongoDB connection.
    """
    global _task_manager

    # ── Startup ─────────────────────────────────────────────────────────
    logger.info("Starting HTTP Metadata Inventory Service...")
    await connect_to_mongodb()

    repository = MetadataRepository()
    _task_manager = BackgroundTaskManager(repository=repository)
    init_routes(repository=repository, task_manager=_task_manager)

    logger.info("Application startup complete.")

    yield

    # ── Shutdown ────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    if _task_manager:
        await _task_manager.cancel_all()
    await close_mongodb_connection()
    logger.info("Shutdown complete.")


# ── App Instance ────────────────────────────────────────────────────────────

app = FastAPI(
    title="HTTP Metadata Inventory Service",
    description=(
        "A service that collects and caches HTTP metadata (headers, cookies, "
        "and page source) for any given URL. Supports synchronous collection "
        "via POST and smart retrieval via GET with automatic background "
        "collection on cache misses."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Register routes
app.include_router(metadata_router)


# ── Global Exception Handlers ──────────────────────────────────────────────


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all handler to prevent 500 errors from leaking stack traces."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error_type": "internal_error",
        },
    )


# ── Health Check ────────────────────────────────────────────────────────────


@app.get(
    "/health",
    tags=["system"],
    summary="Health check",
    description="Returns the health status of the service.",
)
async def health_check():
    """Simple health check endpoint for Docker and monitoring."""
    return {"status": "healthy", "service": "metadata-inventory"}


# ── Root redirect ────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to the interactive API docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")
