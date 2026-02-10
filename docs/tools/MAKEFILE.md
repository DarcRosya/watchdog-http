# 📘 Makefile Guide

## Makefile Structure for Watchdog HTTP

### 1. Development

```bash
make install    # Install dependencies via Poetry
make dev        # Run API server in development mode
make worker     # Run ARQ worker for background tasks
make ui         # Run Streamlit UI dashboard
```

**When to use:**
- `make install` — on initial project setup or after dependency updates
- `make dev` — each time you start working on the API
- `make worker` — for testing background monitoring tasks
- `make ui` — for working with the user interface

### 2. Code Quality

```bash
make format     # Format code with Black
make lint       # Type check with mypy
make test       # Run tests with pytest
make check      # Run all checks (format + lint)
```

**When to use:**
- `make format` — before every commit
- `make lint` — to find type errors
- `make test` — before pushing to repository
- `make check` — comprehensive check before release

### 3. Database

```bash
make migrate    # Create new migration (will ask for description)
make upgrade    # Apply all migrations to DB
make downgrade  # Rollback last migration
make db-reset   # Full DB reset (with confirmation)
```

**When to use:**
- `make migrate` — after changing SQLAlchemy models
- `make upgrade` — when starting project or after pulling new migrations
- `make downgrade` — if you need to rollback changes
- `make db-reset` — for clean DB (on dev environment)

### 4. Docker

```bash
make docker-build    # Build Docker images
make docker-up       # Start all services
make docker-down     # Stop all services
make docker-logs     # Show logs (service=api for specific)
make docker-restart  # Restart all services
make docker-clean    # Remove everything (with confirmation)
```

**When to use:**
- `make docker-up` — to run full stack (API + Worker + DB + Redis)
- `make docker-logs` — for debugging issues
- `make docker-restart` — after configuration changes
- `make docker-clean` — for complete cleanup when having problems

### 5. Version Management

```bash
make sync-version VERSION=1.6.0   # Set version in all files
```

**When to use:**
- Before releasing a new version
- When preparing for Git tagging

### 6. Cleanup

```bash
make clean       # Remove temporary files (__pycache__, .pyc, etc.)
make clean-logs  # Remove log files
```

**When to use:**
- When having import issues (old .pyc files)
- To free up disk space
- Before archiving the project

### 7. Setup

```bash
make setup      # Full project setup (install + pre-commit + upgrade)
make pre-commit # Install Git pre-commit hooks
make info       # Show project information
```

**When to use:**
- `make setup` — on first project clone
- `make pre-commit` — to setup automatic checks on commit
- `make info` — for quick overview of version and settings

---

## How Makefile Works

### Basic Syntax

```makefile
target: dependencies  ## Command description
	@command1
	@command2
```

- **target** — command name (what you type after `make`)
- **dependencies** — other targets that need to be executed first
- **@** — hides command output (shows only result)
- **##** — comment shown in `make help`

### Example from Our Makefile

```makefile
dev: ## Run development server with auto-reload
	@echo "$(BLUE)Starting development server...$(NC)"
	cd src && poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

What happens when calling `make dev`:
1. Prints blue message "Starting development server..."
2. Changes to `src` directory
3. Runs uvicorn through Poetry

### Variables in Makefile

```makefile
BLUE := \033[0;34m    # Color for output
NC := \033[0m         # Reset color

docker-logs:
	docker-compose logs -f $(service)
```

Usage: `make docker-logs service=api`

---

## Useful Tips

### 1. Command Help

```bash
make help    # Show all available commands with descriptions
```

### 2. Command Chaining

Makefile automatically executes dependencies:

```makefile
setup: install pre-commit upgrade
```

`make setup` will execute all three commands in order.

### 3. Confirmation for Dangerous Operations

```bash
make db-reset
# Will ask: "Are you sure? [y/N]"
```

### 4. Conditional Logic

```bash
make docker-logs              # Logs of all services
make docker-logs service=api  # Logs of API only
```

---

## Typical Workflow

### First Project Launch

```bash
git clone <repo>
cd watchdog-http
make setup              # Full setup
make docker-up          # Start infrastructure
```

### Daily Development

```bash
make dev                # Start API
make worker             # In another terminal - worker
# Make code changes
make format             # Formatting
make test               # Testing
git commit              # Pre-commit will automatically check code
```

### Working with Database

```bash
# Modified models/monitor.py
make migrate            # Create migration
make upgrade            # Apply to DB
```

### Releasing New Version

```bash
make sync-version VERSION=1.6.0
git add .
git commit -m "Release v1.6.0"
git tag v1.6.0
git push --tags
```

---