"""
Background task manager for asynchronous metadata collection.

Handles scheduling, deduplication, and lifecycle management of
background asyncio tasks. This avoids external service-to-self
HTTP calls and external queues — all orchestration is internal.
"""

import asyncio
import logging

from app.models.schemas import MetadataDocument
from app.repositories.metadata_repo import MetadataRepository
from app.services.collector import CollectionError, collect_metadata

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """
    Manages background asyncio tasks for metadata collection.

    Key features:
    - Deduplication: only one collection task per URL at a time.
    - Cleanup: completed/failed tasks are cleaned from tracking.
    - Graceful shutdown: all pending tasks can be cancelled.
    """

    def __init__(self, repository: MetadataRepository | None = None) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._repository = repository or MetadataRepository()

    def schedule_collection(self, url: str) -> bool:
        """
        Schedule a background metadata collection for the given URL.

        If a task for this URL is already in-flight, the request is
        deduplicated and no new task is created.

        Args:
            url: The URL to collect metadata for.

        Returns:
            True if a new task was created, False if already in-flight.
        """
        # Clean up finished tasks first
        self._cleanup_completed()

        if url in self._tasks and not self._tasks[url].done():
            logger.info("Collection already in progress for %s, skipping.", url)
            return False

        task = asyncio.create_task(
            self._collect_and_store(url),
            name=f"collect:{url}",
        )
        self._tasks[url] = task
        logger.info("Scheduled background collection for %s", url)
        return True

    async def _collect_and_store(self, url: str) -> None:
        """
        Internal coroutine: fetch metadata and persist to database.

        Runs independently of the request-response cycle.
        """
        try:
            document: MetadataDocument = await collect_metadata(url)
            await self._repository.upsert_metadata(document)
            logger.info("Background collection completed for %s", url)

        except CollectionError as exc:
            logger.error(
                "Background collection failed for %s: %s", url, exc.reason
            )
        except Exception:
            logger.exception("Unexpected error during background collection for %s", url)

    def _cleanup_completed(self) -> None:
        """Remove references to tasks that have already finished."""
        completed = [url for url, task in self._tasks.items() if task.done()]
        for url in completed:
            del self._tasks[url]

    async def cancel_all(self) -> None:
        """
        Cancel all in-flight tasks and wait for them to finish.

        Called during application shutdown for a clean exit.
        """
        if not self._tasks:
            return

        logger.info("Cancelling %d background tasks...", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()

        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("All background tasks cancelled.")

    @property
    def active_task_count(self) -> int:
        """Return the number of currently active tasks."""
        self._cleanup_completed()
        return len(self._tasks)

    def get_task_status(self, url: str) -> str:
        """
        Return the collection task status for a given URL.

        Returns:
            "pending"   — a background task is currently running for this URL.
            "not_found" — no active task exists (either never scheduled,
                          already completed, or previously failed).
        """
        task = self._tasks.get(url)
        if task is not None and not task.done():
            return "pending"
        return "not_found"

