# Environment Variables

Watchdog uses two env files:

| File | Purpose |
| :--- | :--- |
| `.env` | Production / local development stack |
| `.env.test` | Isolated test infrastructure |

Copy the examples before first use:

```bash
cp .env.example .env
cp .env.test.example .env.test
```

---

## `.env` — Main Application

### Database (`DB__*`)

The app uses **TimescaleDB** (PostgreSQL-compatible), accessed via asyncpg.

| Variable | Required | Example | Description |
| :--- | :--- | :--- | :--- |
| `DB__HOST` | Yes | `localhost` | Hostname. In Docker Compose set to `database` (service name). |
| `DB__PORT` | Yes | `5432` | Port. Default PostgreSQL port. |
| `DB__USER` | Yes | `watchdog` | Database user. |
| `DB__PASS` | Yes | `strongpassword` | Database password. |
| `DB__NAME` | Yes | `watchdog` | Database name. |

#### Connection pool tuning (optional)

These settings control SQLAlchemy's async connection pool. Keep
`DB__POOL_SIZE + DB__MAX_OVERFLOW` below Postgres `max_connections`, and leave
headroom for migrations, Grafana, and ad-hoc sessions.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DB__POOL_SIZE` | `26` | Base pool size per process. |
| `DB__MAX_OVERFLOW` | `4` | Extra connections beyond the pool. |
| `DB__POOL_TIMEOUT` | `30.0` | Seconds to wait for a free connection. |
| `DB__POOL_RECYCLE` | `1800` | Recycle connections after this many seconds. |

> **Docker Compose override**: `app`, `monitoring-worker`, and `alerting-worker` always override `DB__HOST=database` and `REDIS__R_HOST=redis` via their `environment:` block — you only need to set credentials in `.env`.

### Redis (`REDIS__*`)

| Variable | Required | Example | Description |
| :--- | :--- | :--- | :--- |
| `REDIS__R_HOST` | Yes | `localhost` | Hostname. In Docker Compose automatically overridden to `redis`. |
| `REDIS__R_PORT` | Yes | `6379` | Port. |

### Telegram (`TELEGRAM__*`)

Required for alert delivery. Without these, the alerting worker starts but all alerts are silently skipped.

| Variable | Required | Example | Description |
| :--- | :--- | :--- | :--- |
| `TELEGRAM__BOT_TOKEN` | Yes | `123456:ABC-xyz…` | Token from [@BotFather](https://t.me/BotFather). |

### Application Flags

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DEBUG_MODE` | `False` | Enables human-readable logs and FastAPI debug mode. Keep `False` in production. |
| `ENABLE_FILE_LOGGING` | `False` | Writes structured JSON logs to `logs/` directory. |

### Grafana (optional)

Used only when running the monitoring stack in Docker Compose.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana admin username. |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password. |

### Full example

```dotenv
DEBUG_MODE=False
ENABLE_FILE_LOGGING=False

DB__HOST=localhost
DB__PORT=5432
DB__USER=watchdog
DB__PASS=strongpassword
DB__NAME=watchdog

REDIS__R_HOST=localhost
REDIS__R_PORT=6379

TELEGRAM__BOT_TOKEN=123456789:AABBccDDeeFFggHH-xxxxxxxxxxxxxxxxxx
```

---

## `.env.test` — Test Infrastructure

Used exclusively by pytest and `docker-compose.test.yml`. The test stack runs on different ports so it can coexist with the main stack without touching production data.

| Variable | Value | Notes |
| :--- | :--- | :--- |
| `DB__USER` | any | Must match the user in `docker-compose.test.yml` |
| `DB__PASS` | any | Must match the password in `docker-compose.test.yml` |
| `DB__HOST` | `localhost` | Test containers are port-forwarded to the host |
| `DB__PORT` | `5433` | Host port for test PostgreSQL (`docker-compose.test.yml` maps `${DB__PORT:-5433} -> 5432`) |
| `DB__NAME` | `watchdog_test` | Hard-coded in `docker-compose.test.yml`; **do not change** |
| `REDIS__HOST` | `localhost` | — |
| `REDIS__PORT` | `6380` | Host port for test Redis (`docker-compose.test.yml` maps `${REDIS__PORT:-6380} -> 6379`); pytest uses Redis **DB 15** |
| `TELEGRAM__BOT_TOKEN` | any / empty | Tests mock the Telegram client; an actual token is not needed |

> **Why a separate `.env.test`?**
> `pytest-dotenv` loads `.env.test` automatically (configured in `pytest.ini` via `env_files = .env.test`). This guarantees that test runs never touch the production database, even when both stacks are up.

### Full example

```dotenv
DEBUG_MODE=True
ENABLE_FILE_LOGGING=False

DB__USER=postgres
DB__PASS=postgres
DB__HOST=localhost
DB__PORT=5433
DB__NAME=watchdog_test

REDIS__HOST=localhost
REDIS__PORT=6380

TELEGRAM__BOT_TOKEN=fake-token-for-tests
```
