# Testing Guide

The test suite is split into **unit** and **integration** tests. Unit tests run with no external dependencies. Integration tests require a live PostgreSQL (TimescaleDB) and Redis instance.

---

## Directory Layout

```
src/tests/
├── conftest.py                         # shared fixtures (DB, Redis, HTTP client, factories)
│
├── unit/                               # no I/O, fully mocked
│   ├── test_schemas_monitor.py         # Pydantic schema validation
│   ├── test_schemas_user.py
│   ├── test_services_monitor.py        # service layer (DB + Redis mocked)
│   ├── test_telegram_notifier.py       # TelegramNotifier + message builders
│   ├── test_utils.py                   # utility functions
│   ├── test_worker_alerting.py         # alerting worker tasks
│   └── test_worker_monitoring.py       # monitoring worker + scheduler
│
└── integration/                        # require live DB + Redis
    ├── test_api_monitors.py            # HTTP endpoints — monitors
    ├── test_api_users.py               # HTTP endpoints — users
    ├── test_repositories_monitor.py    # MonitorRepository against real DB
    ├── test_repositories_resultlog.py  # ResultLogRepository against real DB
    ├── test_repositories_user.py       # UserRepository against real DB
    └── test_services_monitor.py        # MonitorService with real DB + Redis
```

---

## Test Markers

Markers are declared in `pytest.ini` and can be used to run subsets.

| Marker | What it selects |
| :--- | :--- |
| `unit` | Unit tests (no external services needed) |
| `integration` | All integration tests |
| `api` | HTTP endpoint tests |
| `repository` | Repository layer tests |
| `service` | Service layer tests |

```bash
# Run only unit tests
cd src && poetry run pytest tests -m unit

# Run only repository tests
cd src && poetry run pytest tests -m repository

# Run only API tests
cd src && poetry run pytest tests -m api
```

---

## Prerequisites

### Python environment

All development dependencies (pytest, pytest-asyncio, faker, httpx, etc.) are declared in `src/pyproject.toml` under `[tool.poetry.group.dev.dependencies]`.

```bash
make install      # installs both src/ and ui/ dependencies via Poetry
```

### Environment file

pytest loads `.env.test` automatically via `pytest-dotenv` (configured in `pytest.ini`).

```bash
cp .env.test.example .env.test
# then fill in credentials — see docs/configuration/ENV.md
```

---

## Running Unit Tests (no Docker needed)

Unit tests mock all I/O and can run immediately after installing dependencies.

```bash
make test               # runs full suite (unit + integration)

# or target just units
cd src && poetry run pytest tests/unit -v
```

---

## Running Integration Tests

Integration tests hit a real database and Redis. The project provides a dedicated **test infrastructure** that runs in Docker, isolated on different host ports so it can coexist with the main stack.

### Step 1 — Configure `.env.test`

The test containers are port-forwarded to the host:

| Service | Host port | Container port |
| :--- | :--- | :--- |
| PostgreSQL (test) | `5433` | `5432` |
| Redis (test) | `6380` | `6379` |

Your `.env.test` must point to these host ports:

```dotenv
DB__USER=postgres
DB__PASS=postgres
DB__HOST=localhost
DB__PORT=5433
DB__NAME=watchdog_test

REDIS__HOST=localhost
REDIS__PORT=6380

TELEGRAM__BOT_TOKEN=fake-token-for-tests
DEBUG_MODE=True
ENABLE_FILE_LOGGING=False
```

### Step 2 — Start test containers

```bash
make test-infra-up
```

This command starts `docker-compose.test.yml` and waits until both containers report `healthy` status. The database is created in RAM (`tmpfs`) — data is lost when containers stop, which is intentional.

### Step 3 — Run the full suite

```bash
make test
# or with coverage
make test-cov
```

### Step 4 — Stop containers

```bash
make test-infra-down    # stops containers and discards all data
```

---

## Database Isolation

Every integration test gets a fully isolated database session:

1. A `connection` is opened and a `BEGIN` transaction is started.
2. The test runs against this connection.
3. After the test, the transaction is **rolled back** — no data persists.

This means the test database never accumulates state between tests, and you never need to wipe it manually.

The session-scoped `db_engine` fixture creates all tables once at the start of the test session  and drops them at the end.

---

## Fixtures

All shared fixtures live in `src/tests/conftest.py`.

### Database

| Fixture | Scope | Description |
| :--- | :--- | :--- |
| `db_engine` | session | Creates the async engine; creates and drops all tables once. |
| `db_session` | function | Opens a connection with a savepoint; rolls back after each test. |

### Redis

| Fixture | Scope | Description |
| :--- | :--- | :--- |
| `redis_client` | session | Connects to test Redis on DB 15. |
| `clean_redis` | function | Flushes the Redis DB before a test (use when Redis state matters). |

### HTTP Client

| Fixture | Scope | Description |
| :--- | :--- | :--- |
| `client` | function | HTTPX `AsyncClient` wired to the FastAPI app via `ASGITransport`. DB and Redis dependencies are overridden. |

### Factories

| Fixture | Scope | Description |
| :--- | :--- | :--- |
| `create_user(username, api_key, telegram_chat_id)` | function | Creates and commits a `User`; all fields optional (defaults are random). |
| `create_monitor(user_id, name, url, method, interval, …)` | function | Creates and commits a `Monitor`. |

### Pre-built data

| Fixture | Scope | Description |
| :--- | :--- | :--- |
| `sample_user` | function | A `User` with a fixed API key (`test-api-key-1234…`). |
| `sample_monitors` | function | Three monitors pre-assigned to `sample_user`. |
| `auth_headers` | function | `{"X-API-Key": sample_user.api_key}` — ready to pass to client calls. |
| `mock_redis` | function | `AsyncMock(spec=Redis)` for unit tests that need a Redis object without a real connection. |

---

## Coverage

```bash
make test-cov
```

Generates a terminal report and an HTML report at `src/htmlcov/index.html`.

---

## Async Configuration

All tests use `asyncio_mode = auto` (configured in `pytest.ini`). You do not need to decorate test functions with `@pytest.mark.asyncio` — any `async def test_*` function is picked up automatically.

The event loop is function-scoped by default (`asyncio_default_fixture_loop_scope = function`), which prevents state leakage between tests.
