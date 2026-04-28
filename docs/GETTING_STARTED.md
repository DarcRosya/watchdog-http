# Getting Started

This guide walks through every step needed to get Watchdog running — from cloning the repository to having a fully operational monitoring stack or a working test environment.

---

## Requirements

| Dependency | Minimum version | Notes |
| :--- | :--- | :--- |
| Python | 3.12 | Managed by Poetry from project root |
| Poetry | 1.8+ | `pip install poetry` |
| Docker | 24+ | Required for the full stack |
| Docker Compose | v2 (`docker compose`) | Shipped with modern Docker Desktop |
| make | any | Available on Linux/macOS; Windows users can run commands manually |
| Platform support | | This project is intended for Unix-like environments (Linux and macOS). Native Windows execution via CMD or PowerShell is not supported. Windows users should use WSL2 or a compatible Unix-like environment. |


---

## 1. Clone and install dependencies

```bash
git clone <repo-url> watchdog-http
cd watchdog-http
make install
```

`make install` runs a single `poetry install` from the project root.

Optionally install pre-commit hooks (runs Black + mypy before every commit):

```bash
make pre-commit
```

---

## 2. Configuration

### Production / development

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```dotenv
# Database credentials (any values you choose)
DB__HOST=localhost
DB__PORT=5432
DB__USER=watchdog
DB__PASS=changeme
DB__NAME=watchdog

# Redis (default port)
REDIS__R_HOST=localhost
REDIS__R_PORT=6379

# Telegram bot token from @BotFather
TELEGRAM__BOT_TOKEN=123456789:AABBcc...

# Optional flags
DEBUG_MODE=False
ENABLE_FILE_LOGGING=False
```

See [docs/configuration/ENV.md](configuration/ENV.md) for the full variable reference.

### Enable hot reload (development only)

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
```

When this file is present, Docker Compose automatically adds `--reload` / `--watch` flags and mounts the source code into the containers, so code changes take effect immediately without rebuilding.

---

## 3. Starting the full stack

```bash
make docker-up
```

This builds all images (first run) and starts:

| Service | Accessible at |
| :--- | :--- |
| Nginx (entry point) | http://localhost:80 |
| Root redirect | http://localhost:80/ -> /docs |
| FastAPI (via Nginx) | http://localhost:80/api/ |
| Swagger UI | http://localhost:80/docs |
| ReDoc | http://localhost:80/redoc |
| Raw FastAPI (direct) | http://localhost:8000 — only if override file adds port forwarding |

Monitoring stack endpoints:

| Service | URL | Notes |
| :--- | :--- | :--- |
| Grafana | http://localhost:3000 | Default login: `admin` / `admin` (override via `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`) |
| Prometheus | http://localhost:9090 | Scrapes API and Pushgateway |
| Pushgateway | http://localhost:9091 | Worker metrics ingestion |

Wait a few seconds for the database health check to pass, then the API and workers will start automatically.

Check that everything is up:

```bash
docker compose ps
# or
make docker-logs
```

---

## 4. Apply database migrations

The database schema is managed by Alembic. On a fresh install, run:

```bash
make upgrade
```

This applies all migrations in `src/migrations/versions/` to bring the schema to the latest state.

After changing SQLAlchemy models, generate and apply a new migration:

```bash
make migrate    # prompts for a migration description
make upgrade    # applies it
```

---

## 5. Using the API

The API is authenticated via an `X-API-Key` header.

### Create a new user (get your API key)

```bash
curl -X POST http://localhost/api/users/
# Response: {"id": 1, "username": "bold-jaguar", "api_key": "abc123...", ...}
```

### Add a monitor

```bash
curl -X POST http://localhost/api/monitors/add-urls \
  -H "X-API-Key: abc123..." \
  -H "Content-Type: application/json" \
  -d '[{"url": "https://example.com", "name": "Example", "interval": 60}]'
```

### List your monitors

```bash
curl http://localhost/api/monitors/ \
  -H "X-API-Key: abc123..."
```

Full API documentation is available at **http://localhost/docs** (Swagger UI) and **http://localhost/redoc** (ReDoc).

---

## 6. Setting up Telegram alerts

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token.
2. Set `TELEGRAM__BOT_TOKEN` in `.env`.
3. Start a conversation with your bot, then find your chat ID (e.g., via `@userinfobot`).
4. Link your Telegram ID to your Watchdog account:

```bash
curl -X PATCH http://localhost/api/users/me \
  -H "X-API-Key: abc123..." \
  -H "Content-Type: application/json" \
  -d '{"telegram_chat_id": 123456789}'
```

From this point on, the alerting worker will send you notifications when a monitor goes down or recovers.

---

## 7. Setting up the test environment

### Configure `.env.test`

```bash
cp .env.test.example .env.test
```

Edit `.env.test` and set host ports for test containers.
Defaults are `5433` for PostgreSQL and `6380` for Redis.
If these ports are busy on your machine, choose any free ports and keep `.env.test` in sync.

```dotenv
DB__USER=postgres
DB__PASS=postgres
DB__HOST=localhost
DB__PORT=5433       # ← host-forwarded port from docker-compose.test.yml
DB__NAME=watchdog_test

REDIS__HOST=localhost
REDIS__PORT=6380    # ← host-forwarded port from docker-compose.test.yml

TELEGRAM__BOT_TOKEN=fake-token-for-tests
DEBUG_MODE=True
ENABLE_FILE_LOGGING=False
```

### Start test containers

```bash
make test-infra-up
```

The command starts isolated PostgreSQL and Redis containers with in-RAM storage and waits until both are healthy. Published host ports are taken from `.env.test` (`DB__PORT` and `REDIS__PORT`).

### Run the test suite

```bash
make test           # all tests
make test-cov       # with HTML coverage report (src/htmlcov/)
```

### Stop containers

```bash
make test-infra-down
```

For a detailed breakdown of the test architecture, fixtures, and markers, see [docs/testing/TESTING.md](testing/TESTING.md).

---

## 8. Helpful commands

```bash
make help           # list all available make targets

make check          # format (Black) + type check (mypy)
make docker-logs    # stream all container logs
make docker-logs service=app   # stream logs from one service
make docker-restart # stop + start all containers
make db-reset       # wipe and re-create the schema (asks for confirmation)
make clean          # remove __pycache__, .pytest_cache, .mypy_cache
make sync-version SET=2.0.0    # bump version in README, pyproject.toml, main.py
```

---

## 9. Stopping the stack

```bash
make docker-down          # stop containers (data is preserved in volumes)
make docker-clean         # stop + remove containers, volumes, and images (asks for confirmation)
```

---

## Troubleshooting

**`make upgrade` fails with "could not connect"**
The database container may not be ready yet. Run `docker compose ps` — the `database` service should show `healthy`. If it does not, check credentials in `.env`.

**Tests fail with "Redis unavailable"**
Make sure test containers are running (`make test-infra-up`) and that `.env.test` has the same `REDIS__PORT` value you configured for test containers.

**Telegram alerts are not arriving**
Check that `TELEGRAM__BOT_TOKEN` is set, the `telegram_chat_id` is linked to your user, and the alerting worker is running:

```bash
docker compose logs alerting-worker
```

**Hot reload is not working**
Verify that `docker-compose.override.yml` exists in the project root:

```bash
ls docker-compose.override.yml
```
