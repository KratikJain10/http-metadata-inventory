# HTTP Metadata Inventory Service

A high-performance, asynchronous HTTP metadata collection and caching service built with **FastAPI** and **MongoDB**. It fetches and stores HTTP headers, cookies, and full page source for any URL — with smart cache-miss handling via background workers.

---

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Design Decisions](#design-decisions)
- [Extensibility](#extensibility)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        FastAPI Application                   │
│                                                              │
│   ┌────────────────┐        ┌─────────────────────────────┐  │
│   │ POST /metadata │        │ GET /metadata               │  │
│   │ (sync collect  │        │  ├─ cache hit  → 200 + data │  │
│   │  + store)      │        │  └─ cache miss → 202 + bg   │  │
│   └───────┬────────┘        └───────┬─────────────────────┘  │
│           │                         │                        │
│   ┌───────▼─────────────────────────▼────────────────────┐   │
│   │                  Service Layer                        │   │
│   │  ┌──────────────────┐  ┌──────────────────────────┐  │   │
│   │  │ MetadataCollector │  │ BackgroundTaskManager    │  │   │
│   │  │ (httpx async)    │  │ (asyncio.Task + dedup)   │  │   │
│   │  └──────────────────┘  └──────────────────────────┘  │   │
│   └──────────────────────────┬───────────────────────────┘   │
│                              │                               │
│   ┌──────────────────────────▼───────────────────────────┐   │
│   │               Repository Layer                        │   │
│   │               MetadataRepository                      │   │
│   │               (find / upsert / delete)                │   │
│   └──────────────────────────┬───────────────────────────┘   │
└──────────────────────────────┼───────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │     MongoDB 7       │
                    │  (indexed on url)   │
                    └─────────────────────┘
```

### Request Flow

1. **POST `/metadata`** — Client sends a URL → the service fetches its HTTP metadata synchronously → stores it in MongoDB → returns `201 Created` with the full dataset.

2. **GET `/metadata`** (cache hit) — Client queries a URL → metadata found in database → returns `200 OK` with the full dataset immediately.

3. **GET `/metadata`** (cache miss) — Client queries a URL → metadata not found → returns `202 Accepted` instantly → spawns an internal `asyncio.Task` to collect and persist the data in the background → subsequent GET requests will return `200` with the data.

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

### Run the Service

```bash
# Clone the repository
git clone https://github.com/KratikJain10/http-metadata-inventory.git
cd http-metadata-inventory

# Start the API and MongoDB
docker-compose up --build
```

The API will be available at **http://localhost:8000**

Interactive Swagger docs at **http://localhost:8000/docs**

### Stop the Service

```bash
docker-compose down

# To also remove the MongoDB data volume:
docker-compose down -v
```

---

## API Reference

### `POST /metadata` — Collect & Store

Fetches the given URL and stores its HTTP headers, cookies, and page source.

**Request:**
```bash
curl -X POST "http://localhost:8000/metadata" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Response — `201 Created`:**
```json
{
  "url": "https://example.com",
  "headers": {
    "content-type": "text/html; charset=UTF-8",
    "server": "cloudflare",
    "age": "3627"
  },
  "cookies": {},
  "page_source": "<!doctype html><html>...</html>",
  "collected_at": "2026-03-03T17:11:45.079610Z"
}
```

**Error Responses:**
| Code | Condition |
|------|-----------|
| `422` | Invalid URL format (e.g., `"123"`, missing scheme) |
| `502` | Target URL unreachable, timed out, or returned an error |

---

### `GET /metadata` — Retrieve (with auto-collection)

Retrieves stored metadata for a URL. If not found, triggers asynchronous background collection.

**Request:**
```bash
curl "http://localhost:8000/metadata?url=https://example.com"
```

**Response — `200 OK` (cache hit):**
```json
{
  "url": "https://example.com",
  "headers": { "content-type": "text/html", "...": "..." },
  "cookies": {},
  "page_source": "<!doctype html>...",
  "collected_at": "2026-03-03T17:11:45.079610Z"
}
```

**Response — `202 Accepted` (cache miss → background collection triggered):**
```json
{
  "message": "Request accepted. Metadata collection has been scheduled.",
  "url": "https://httpbin.org/html",
  "status": "pending"
}
```

> After a few seconds, a subsequent `GET` will return `200` with the collected data.

**Error Responses:**
| Code | Condition |
|------|-----------|
| `422` | Invalid URL format or missing `url` query parameter |

---

### `GET /health` — Health Check

```bash
curl http://localhost:8000/health
```
```json
{"status": "healthy", "service": "metadata-inventory"}
```

---

## Testing

### Run Tests Inside Docker (Recommended)

```bash
docker-compose run --rm api pytest -v
```

### Run Tests Locally

```bash
# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the test suite (uses mongomock — no real MongoDB needed)
pytest -v
```

### Test Suite Summary

| Suite | Count | What's Tested |
|-------|-------|---------------|
| `test_collector.py` | 6 | Successful fetch, cookie extraction, redirect following, timeout handling, connection errors, large payloads |
| `test_repository.py` | 6 | Upsert, find, replace, delete, count, upsert idempotency |
| `test_api.py` | 9 | POST `201`/`422`/`502`, GET `200`/`202`/`422`, background collection end-to-end, health check |
| **Total** | **21** | |

---

## Project Structure

```
├── app/
│   ├── main.py                 # FastAPI app factory + lifespan (startup/shutdown)
│   ├── config.py               # Pydantic Settings (env-based configuration)
│   ├── database.py             # Motor async MongoDB client + retry logic + indexing
│   ├── models/
│   │   └── schemas.py          # Pydantic request/response/document models
│   ├── repositories/
│   │   └── metadata_repo.py    # MongoDB CRUD operations (data access layer)
│   ├── services/
│   │   ├── collector.py        # HTTP metadata fetcher (httpx async)
│   │   └── background.py       # Background task manager (asyncio + dedup)
│   └── routes/
│       └── metadata.py         # API endpoint handlers
├── tests/
│   ├── conftest.py             # Shared fixtures (mock DB, test client, sample data)
│   ├── test_collector.py       # Collector service unit tests
│   ├── test_repository.py      # Repository layer unit tests
│   └── test_api.py             # API integration tests
├── Dockerfile                  # Multi-stage build, non-root user, SSL certs
├── docker-compose.yml          # API + MongoDB 7 with healthchecks
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
└── .gitignore
```

---

## Configuration

All settings are managed via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://mongodb:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `metadata_inventory` | Database name |
| `REQUEST_TIMEOUT` | `30` | HTTP request timeout in seconds |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Layered architecture** (routes → services → repos → DB) | Clear separation of concerns; each layer is independently testable and replaceable |
| **`asyncio.Task` for background work** | Satisfies the "internal logic orchestration" constraint — no external queues, no self-HTTP calls, no polling loops |
| **Task deduplication** | Multiple GET requests for the same uncached URL only spawn one background task |
| **`httpx.AsyncClient`** | Production-grade async HTTP client with redirect following, timeout handling, and connection pooling |
| **`motor` async MongoDB driver** | Non-blocking database I/O for efficient resource utilisation |
| **MongoDB unique index on `url`** | O(1) lookups and upsert idempotency as dataset grows |
| **Exponential backoff on startup** | API survives Docker Compose startup ordering (MongoDB may not be ready immediately) |
| **Multi-stage Dockerfile** | Smaller image size; non-root user for security |
| **`mongomock-motor` for tests** | Tests run without a real MongoDB instance — fast, isolated, CI-friendly |

---

## Extensibility

The layered architecture makes it straightforward to extend:

- **Message queue**: Replace `BackgroundTaskManager` with Celery/RabbitMQ workers — routes and repository remain untouched.
- **Redis caching**: Insert a cache layer between routes and repository for sub-millisecond reads.
- **New endpoints**: Add `DELETE /metadata`, `GET /metadata/list`, or batch collection endpoints.
- **Database swap**: The repository pattern abstracts MongoDB — implement a new repository class for PostgreSQL or any other store.
- **Distributed deployment**: Split the background worker into a separate service communicating via a message broker.
