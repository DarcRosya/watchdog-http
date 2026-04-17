# Docker Compose Configuration

The project ships three Compose files that cover every scenario.

---

## File Overview

| File | Purpose | When to use |
| :--- | :--- | :--- |
| `docker-compose.yml` | Production stack — all services, no port exposure | Deployment / full local run |
| `docker-compose.override.yml` | Dev additions — hot reload, source mounts | Applied automatically when present |
| `docker-compose.override.example.yml` | Template for the override file | Copy and enable once |
| `docker-compose.test.yml` | Isolated test infrastructure | `make test-infra-up` before running tests |

---

## `docker-compose.yml` — Production Stack

Defines seven services. All internal communication goes over the Docker network by service name. No host ports are exposed except Nginx on `:80`.

```
Internet → Nginx :80
               ├── /api/*         → app :8000  (FastAPI)
               ├── /docs, /redoc  → app :8000
               └── /              → ui  :8501  (Streamlit)

app            → database :5432  (TimescaleDB)
app            → redis    :6379
monitoring-worker → database, redis
alerting-worker   → database, redis
telegram-bot      → database
```

### Build Strategy

- Backend services (`app`, `migrator`, workers, `telegram-bot`) build from project root context (`.`) using `src/Dockerfile` and `target: prod`.
- `migrator` reuses the same backend image and runs `alembic -c src/alembic.ini upgrade head`.
- `ui` builds from project root context (`.`) with `ui/Dockerfile`.
- Development mode overrides backend `target` to `dev` in `docker-compose.override.yml` so `--reload` / `--watch` dependencies are present.
- Production compose keeps backend containers immutable; source bind mounts are only in development override.

### Services

#### `database` — TimescaleDB

```yaml
image: timescale/timescaledb:latest-pg14
container_name: watchdog_db
```

- Persists data in named volume `postgres_data`.
- Health-checked via `pg_isready`; dependent services wait for it.
- Credentials come from `.env` (`DB__USER`, `DB__PASS`, `DB__NAME`).

#### `redis` — Cache & Task Queue

```yaml
image: redis:7-alpine
container_name: watchdog_redis
```

- Persists data in named volume `redis_data`.
- Used both as a job queue (ARQ) and as an in-memory config/state store for monitors.

#### `app` — FastAPI Application

```yaml
container_name: watchdog_app
command: uvicorn src.main:app --host 0.0.0.0 --port 8000
```

- Loads `.env` for credentials; `DB__HOST` and `REDIS__R_HOST` are overridden to service names.
- Exposed internally on `:8000`; never directly reachable from the host in production.
- Logs are written to `./logs/` via a bind mount.

#### `monitoring-worker` — Check Scheduler

```yaml
container_name: watchdog_monitoring_worker
command: arq src.worker.monitoring.MonitoringWorkerSettings
```

- Runs the ARQ worker that executes HTTP health checks and manages the Redis scheduler.
- Starts only after both `database` and `redis` are healthy.

#### `alerting-worker` — Notification Dispatcher

```yaml
container_name: watchdog_alerting_worker
command: arq src.worker.alerting.AlertingWorkerSettings
```

- Dequeues alert jobs and forwards them to Telegram.
- Separated from monitoring worker to avoid blocking health checks on Telegram API latency.

#### `telegram-bot` — Interactive Bot

```yaml
container_name: watchdog_telegram
command: python -m src.telegram.bot
```

- Provides a Telegram bot interface for querying monitor status.

#### `ui` — Streamlit Dashboard

```yaml
container_name: watchdog_ui
```

- Internal only (`:8501`); routed from Nginx root `/`.

#### `nginx` — Reverse Proxy

```yaml
container_name: watchdog_nginx
ports:
  - "80:80"
```

- The only service that exposes a host port.
- Routes traffic:
  - `/api/*` → FastAPI
  - `/docs`, `/redoc`, `/openapi.json` → FastAPI
  - `/` → Streamlit
  - `/health` → 200 OK (no upstream hit)

---

## `docker-compose.override.yml` — Development Mode

Docker Compose **automatically merges** this file on every `docker compose` command when it is present. You do not need to reference it explicitly.

What it adds on top of the base file:

| Service | Change |
| :--- | :--- |
| `app` | `--reload` flag for hot reload |
| `monitoring-worker` | `--watch src` for auto-restart on code changes |
| `alerting-worker` | `--watch src` for auto-restart on code changes |
| `telegram-bot` | Bind mount `./src:/app/src` for local bot code edits |
| `app`, `monitoring-worker`, `alerting-worker` | Bind mount `./src:/app/src` so local edits are picked up immediately |

To enable:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
```

To disable (e.g., production-like run on local machine):

```bash
rm docker-compose.override.yml
# or rename it
mv docker-compose.override.yml docker-compose.override.yml.bak
```

---

## `docker-compose.test.yml` — Test Infrastructure

A fully isolated, ephemeral stack. It never shares data or networks with the main stack.

| Difference | Main stack | Test stack |
| :--- | :--- | :--- |
| PostgreSQL port (host) | not exposed | `127.0.0.1:${DB__PORT:-5433}` |
| Redis port (host) | not exposed | `127.0.0.1:${REDIS__PORT:-6380}` |
| Data storage | named volumes (persistent) | `tmpfs` (in RAM, lost on stop) |
| Database name | configurable via `.env` | always `watchdog_test` |

> **Why tmpfs?**
> Tests roll back every transaction via SQLAlchemy savepoints, so no data survives between individual tests anyway. Using RAM storage makes container startup faster and leaves no leftover files.

pytest runs on the host and connects through forwarded host ports.
The test containers expose:
- `127.0.0.1:${DB__PORT:-5433} → container:5432`
- `127.0.0.1:${REDIS__PORT:-6380} → container:6379`

So `.env.test` should have matching values:
```dotenv
DB__PORT=5433
REDIS__PORT=6380
```

> **Note:** If `5433` or `6380` is already occupied, set any free ports in `.env.test` and use the same values when starting test infrastructure.

### Common commands

```bash
# Start test containers
make test-infra-up          # waits for healthy status

# Run tests
make test

# Stop and discard all test data
make test-infra-down
```

---

## Resource Limits

All services have explicit CPU and memory limits (`deploy.resources.limits`). These are enforced by Docker's cgroup integration and protect the host from runaway processes.

| Service | CPU limit | Memory limit |
| :--- | :--- | :--- |
| database | 0.5 | 512 MB |
| redis | 0.25 | 128 MB |
| app | 0.5 | 256 MB |
| monitoring-worker | 0.5 | 384 MB |
| alerting-worker | 0.25 | 128 MB |
| telegram-bot | 0.25 | 128 MB |
| ui | 0.25 | 256 MB |
| nginx | 0.25 | 64 MB |
