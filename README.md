# HTTP Metadata Inventory Service

A FastAPI-based service that collects and caches HTTP metadata (headers, cookies, and page source) for any given URL. Features smart retrieval with automatic background collection on cache misses.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      FastAPI App                        │
│                                                         │
│  ┌───────────────┐    ┌──────────────────────────────┐  │
│  │  POST /metadata│    │  GET /metadata               │  │
│  │  (sync fetch   │    │  ┌─ cache hit  → 200 + data │  │
│  │   + store)     │    │  └─ cache miss → 202 + bg   │  │
│  └───────┬───────┘    └───────┬──────────────────────┘  │
│          │                    │                          │
│  ┌───────▼────────────────────▼──────────────────────┐  │
│  │              Service Layer                         │  │
│  │  ┌─────────────────┐  ┌───────────────────────┐   │  │
│  │  │ MetadataCollector│  │ BackgroundTaskManager │   │  │
│  │  │ (httpx async)   │  │ (asyncio.Task + dedup)│   │  │
│  │  └─────────────────┘  └───────────────────────┘   │  │
│  └───────────────────────────┬───────────────────────┘  │
│                              │                          │
│  ┌───────────────────────────▼───────────────────────┐  │
│  │           Repository Layer                         │  │
│  │           MetadataRepository                       │  │
│  │           (find / upsert / delete)                 │  │
│  └───────────────────────────┬───────────────────────┘  │
└──────────────────────────────┼──────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │     MongoDB 7       │
                    │  (indexed on url)   │
                    └─────────────────────┘
```

### Design Decisions

- **Layered Architecture**: Clear separation between transport (routes), business logic (services), and data access (repositories). Each layer is independently testable.
- **`asyncio.Task` for Background Work**: Cache-miss collection runs as an in-process asyncio task — no external queues, no self-HTTP calls, no polling loops. This satisfies the "internal logic orchestration" constraint.
- **Deduplication**: If multiple GET requests hit the same uncached URL, only one background task runs.
- **Retry on Startup**: MongoDB connection uses exponential backoff, ensuring the API survives Docker Compose startup ordering.

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

### Run the Service

```bash
# Clone the repository
git clone <repo-url>
cd cloudsek_ass

# Start the API and MongoDB
docker-compose up --build
```

The API will be available at **http://localhost:8000**.

Swagger docs: **http://localhost:8000/docs**

### Stop the Service

```bash
docker-compose down
# To also remove the MongoDB data volume:
docker-compose down -v
```

## API Reference

### `POST /metadata`

Collect and store metadata for a URL.

```bash
curl -X POST "http://localhost:8000/metadata" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Response** `201 Created`:
```json
{
  "url": "https://example.com",
  "headers": {
    "content-type": "text/html; charset=UTF-8",
    "age": "526823",
    "...": "..."
  },
  "cookies": {},
  "page_source": "<!doctype html>...",
  "collected_at": "2026-03-03T18:00:00Z"
}
```

### `GET /metadata`

Retrieve metadata for a URL.

**Cache hit** — `200 OK`:
```bash
curl "http://localhost:8000/metadata?url=https://example.com"
```
```json
{
  "url": "https://example.com",
  "headers": {"...": "..."},
  "cookies": {},
  "page_source": "<!doctype html>...",
  "collected_at": "2026-03-03T18:00:00Z"
}
```

**Cache miss** — `202 Accepted` (background collection triggered):
```bash
curl -i "http://localhost:8000/metadata?url=https://httpbin.org/html"
```
```json
{
  "message": "Request accepted. Metadata collection has been scheduled.",
  "url": "https://httpbin.org/html",
  "status": "pending"
}
```

After a few seconds, a subsequent GET will return the collected data.

### `GET /health`

```bash
curl http://localhost:8000/health
# {"status": "healthy", "service": "metadata-inventory"}
```

## Testing

### Run Tests Inside Docker

```bash
docker-compose run --rm api pytest -v
```

### Run Tests Locally

```bash
# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the test suite (uses mongomock — no real DB needed)
pytest -v
```

### Test Coverage

| Area | Tests |
|------|-------|
| **Collector Service** | Successful fetch, cookies, redirects, timeouts, connection errors, large payloads |
| **Repository Layer** | Upsert, find, replace, delete, count |
| **API Endpoints** | POST 201/422/502, GET 200/202/422, background collection flow |
| **Health Check** | 200 response |

## Project Structure

```
├── app/
│   ├── main.py              # App factory + lifespan
│   ├── config.py             # Settings (env vars)
│   ├── database.py           # MongoDB connection + retry
│   ├── models/
│   │   └── schemas.py        # Pydantic models
│   ├── repositories/
│   │   └── metadata_repo.py  # MongoDB CRUD
│   ├── services/
│   │   ├── collector.py      # HTTP metadata fetcher
│   │   └── background.py     # Background task manager
│   └── routes/
│       └── metadata.py       # API endpoints
├── tests/
│   ├── conftest.py           # Test fixtures
│   ├── test_collector.py     # Collector unit tests
│   ├── test_repository.py    # Repository unit tests
│   └── test_api.py           # Integration tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Configuration

All settings are managed via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://mongodb:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `metadata_inventory` | Database name |
| `REQUEST_TIMEOUT` | `30` | HTTP request timeout (seconds) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Extensibility

The layered architecture makes it straightforward to:

- **Add a message queue**: Replace `BackgroundTaskManager` with Celery/RabbitMQ workers without touching routes or repository.
- **Add Redis caching**: Insert a cache layer between routes and repository.
- **Add new endpoints**: e.g., `DELETE /metadata`, `GET /metadata/list`, or batch collection.
- **Switch databases**: The repository pattern abstracts MongoDB — swap to PostgreSQL by implementing a new repository class.
