# Makefile Guide

Quick reference for the current `Makefile` targets. Run `make help` to see the live list.

---

## Common workflows

```bash
make install
cp .env.example .env
make docker-up
```

```bash
make test-infra-up
make test
```

---

## Command reference

### Development

```bash
make install    # Install dependencies via Poetry
make lock       # Update poetry.lock files
make update     # Update dependencies to latest versions
make pre-commit # Install pre-commit hooks
```

### Code quality

```bash
make format     # Format code with Black
make lint       # Type check with mypy
make check      # Format + lint
```

### Testing

```bash
make test-infra-up    # Start isolated test containers
make test-infra-down  # Stop and remove test containers
make test             # Run full test suite
make test-cov         # Run tests with coverage report
```

### Database

```bash
make migrate    # Create new migration (prompts for a message)
make upgrade    # Apply all migrations
make downgrade  # Roll back last migration
make db-reset   # Full DB reset (with confirmation)
```

### Docker

```bash
make docker-build   # Build Docker images
make docker-up      # Start all services
make docker-down    # Stop all services
make docker-logs    # Stream logs (service=<name> for one service)
make docker-restart # Restart all services
make docker-clean   # Remove containers, volumes, and images
```

Example:

```bash
make docker-logs service=app
```

Service name examples: `app`, `monitoring-worker`, `alerting-worker`, `scheduler-worker`, `prometheus`, `grafana`, `nginx`.

### Git & versioning

```bash
make pre-commit-run     # Run pre-commit on all files
make commit             # Format + add + commit with editor
make amend              # Format + add + amend last commit
make sync-version SET=2.0.0
```

### Cleanup & info

```bash
make clean       # Remove caches and temp files
make clean-logs  # Remove log files
make setup       # Install + pre-commit + upgrade
make info        # Show project info
make help        # List all targets
```

---

## See also

- [docs/GETTING_STARTED.md](../GETTING_STARTED.md)
- [docs/testing/TESTING.md](../testing/TESTING.md)
- [docs/tools/VERSION_SYNC.md](./VERSION_SYNC.md)
