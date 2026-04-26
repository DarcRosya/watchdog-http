.PHONY: help install lock update test lint format check clean docker-up docker-down docker-build migrate upgrade downgrade pre-commit commit amend sync-version test-infra-up test-infra-down

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@printf "$(BLUE)Watchdog HTTP - Available Commands$(NC)\n"
	@printf "\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@printf "\n"

## Development Environment

install: ## Install dependencies with Poetry
	@printf "$(BLUE)Installing dependencies...$(NC)\n"
	poetry install
	@printf "$(GREEN)✓ Dependencies installed$(NC)\n"

lock: ## Update poetry.lock files
	@printf "$(BLUE)Updating lock files...$(NC)\n"
	poetry lock
	@printf "$(GREEN)✓ Lock files updated$(NC)\n"

update: ## Update dependencies to latest versions
	@printf "$(BLUE)Updating dependencies...$(NC)\n"
	poetry update
	@printf "$(GREEN)✓ Dependencies updated$(NC)\n"

## Code Quality

lint: ## Run linters (mypy type checking)
	@printf "$(BLUE)Running type checks...$(NC)\n"
	poetry run mypy src
	@printf "$(GREEN)✓ Lint complete$(NC)\n"

format: ## Format code with black
	@printf "$(BLUE)Formatting code...$(NC)\n"
	poetry run black src tests scripts
	@printf "$(GREEN)✓ Code formatted$(NC)\n"

check: format lint ## Run all checks (format + lint)
	@printf "$(GREEN)✓ All checks passed$(NC)\n"

## Testing

test: ## Run all tests (requires test infra: make test-infra-up)
	@printf "$(BLUE)Running all tests...$(NC)\n"
	poetry run pytest tests
	@printf "$(GREEN)✓ Tests complete$(NC)\n"

test-infra-up: ## Start isolated test containers (postgres:$${DB__PORT:-5433}, redis:$${REDIS__PORT:-6380})
	@printf "$(BLUE)Starting test infrastructure...$(NC)\n"
	docker compose -f docker-compose.test.yml --env-file .env.test up -d
	@printf "$(BLUE)Waiting for containers to become healthy...$(NC)\n"
	@for i in $$(seq 1 20); do \
		db_status=$$(docker inspect --format='{{.State.Health.Status}}' watchdog_test_db 2>/dev/null); \
		redis_status=$$(docker inspect --format='{{.State.Health.Status}}' watchdog_test_redis 2>/dev/null); \
		if [ "$$db_status" = "healthy" ] && [ "$$redis_status" = "healthy" ]; then \
			printf "$(GREEN)✓ Test infrastructure ready (postgres:%s, redis:%s)$(NC)\n" "$${DB__PORT:-5433}" "$${REDIS__PORT:-6380}"; \
			exit 0; \
		fi; \
		printf "  waiting... db=$$db_status redis=$$redis_status\n"; \
		sleep 2; \
	done; \
	printf "$(RED)✗ Timeout waiting for test infrastructure$(NC)\n"; exit 1

test-infra-down: ## Stop and remove isolated test containers (data is discarded)
	@printf "$(BLUE)Stopping test infrastructure...$(NC)\n"
	docker compose -f docker-compose.test.yml down -v
	@printf "$(GREEN)✓ Test infrastructure stopped$(NC)\n"

test-cov: ## Run tests with coverage report
	@printf "$(BLUE)Running tests with coverage...$(NC)\n"
	poetry run pytest tests --cov=src --cov-report=term-missing --cov-report=html
	@printf "$(GREEN)✓ Coverage report generated in htmlcov/$(NC)\n"



## Database

migrate: ## Create a new migration
	@printf "$(BLUE)Creating new migration...$(NC)\n"
	@read -p "Migration message: " msg; \
	PYTHONPATH=. poetry run alembic -c alembic.ini revision --autogenerate -m "$$msg"
	@printf "$(GREEN)✓ Migration created$(NC)\n"

upgrade: ## Upgrade database to latest migration
	@printf "$(BLUE)Upgrading database...$(NC)\n"
	PYTHONPATH=. poetry run alembic -c alembic.ini upgrade head
	@printf "$(GREEN)✓ Database upgraded$(NC)\n"

downgrade: ## Downgrade database by one revision
	@printf "$(BLUE)Downgrading database...$(NC)\n"
	PYTHONPATH=. poetry run alembic -c alembic.ini downgrade -1
	@printf "$(GREEN)✓ Database downgraded$(NC)\n"

db-reset: ## Reset database (downgrade all + upgrade head)
	@printf "$(YELLOW)⚠ This will reset the database!$(NC)\n"
	@read -p "Are you sure? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		PYTHONPATH=. poetry run alembic -c alembic.ini downgrade base && PYTHONPATH=. poetry run alembic -c alembic.ini upgrade head; \
		printf "$(GREEN)✓ Database reset complete$(NC)\n"; \
	else \
		printf "$(RED)Aborted$(NC)\n"; \
	fi

## Docker

docker-build: ## Build Docker images
	@printf "$(BLUE)Building Docker images...$(NC)\n"
	docker compose build
	@printf "$(GREEN)✓ Docker images built$(NC)\n"

docker-up: ## Start all services with Docker Compose
	@printf "$(BLUE)Starting Docker services...$(NC)\n"
	docker compose up -d
	@printf "$(GREEN)✓ Services started$(NC)\n"
	@printf "API: http://localhost:8000\n"
	@printf "Docs: http://localhost/docs\n"

docker-down: ## Stop all Docker services
	@printf "$(BLUE)Stopping Docker services...$(NC)\n"
	docker compose down
	@printf "$(GREEN)✓ Services stopped$(NC)\n"

docker-logs: ## Show Docker logs (use service=<name> for specific service)
	@if [ -z "$(service)" ]; then \
		docker compose logs -f; \
	else \
		docker compose logs -f $(service); \
	fi

docker-restart: docker-down docker-up ## Restart all Docker services

docker-clean: ## Remove all containers, volumes and images
	@echo "$(YELLOW)⚠ This will remove all containers, volumes and images!$(NC)"
	@read -p "Are you sure? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		docker compose down -v --rmi all; \
		printf "$(GREEN)✓ Cleanup complete$(NC)\n"; \
	else \
		printf "$(RED)Aborted$(NC)\n"; \
	fi

## Git & Version Management

pre-commit: ## Install pre-commit hooks
	@printf "$(BLUE)Installing pre-commit hooks...$(NC)\n"
	poetry run pre-commit install
	@printf "$(GREEN)✓ Pre-commit hooks installed$(NC)\n"

pre-commit-run: ## Run pre-commit on all files
	@printf "$(BLUE)Running pre-commit hooks...$(NC)\n"
	poetry run pre-commit run --all-files
	@printf "$(GREEN)✓ Pre-commit checks complete$(NC)\n"

commit: ## Smart commit: format + add all changes + open editor
	@make format
	@printf "$(BLUE)Adding all changes...$(NC)\n"
	@git add -A
	@printf "$(BLUE)Opening commit editor...$(NC)\n"
	@if git commit; then \
		printf "$(GREEN)✓ Commit successful$(NC)\n"; \
	else \
		printf "$(YELLOW)Pre-commit made changes, adding and retrying...$(NC)\n"; \
		git add -A; \
		git commit --no-verify; \
		printf "$(GREEN)✓ Commit successful$(NC)\n"; \
	fi

amend: ## Smart amend: format + add all changes + amend last commit
	@make format
	@printf "$(BLUE)Adding all changes...$(NC)\n"
	@git add -A
	@printf "$(BLUE)Amending last commit...$(NC)\n"
	@if git commit --amend; then \
		printf "$(GREEN)✓ Amend successful$(NC)\n"; \
	else \
		printf "$(YELLOW)Pre-commit made changes, adding and retrying...$(NC)\n"; \
		git add -A; \
		git commit --amend --no-verify; \
		printf "$(GREEN)✓ Amend successful$(NC)\n"; \
	fi

sync-version: ## Sync version across all files (usage: make sync-version VERSION=1.6.0)
	@printf "$(BLUE)Syncing version across files...$(NC)\n"
	@if [ -z "$(SET)" ]; then \
		printf "$(RED)Error: VERSION is required$(NC)\n"; \
		printf "Usage: make sync-version SET=1.6.0\n"; \
		exit 1; \
	fi
	@python scripts/sync_version.py $(SET)
	@printf "$(GREEN)✓ Version synced$(NC)\n"

## Cleanup

clean: ## Clean temporary files and caches
	@printf "$(BLUE)Cleaning temporary files...$(NC)\n"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*~" -delete 2>/dev/null || true
	@printf "$(GREEN)✓ Cleanup complete$(NC)\n"

clean-logs: ## Remove log files
	@printf "$(BLUE)Removing log files...$(NC)\n"
	rm -f logs/*.json
	@printf "$(GREEN)✓ Logs cleaned$(NC)\n"

## Complete Setup

setup: install pre-commit upgrade ## Complete setup (install + pre-commit + migrations)
	@printf "\n"
	@printf "$(GREEN)╔════════════════════════════════════════╗$(NC)\n"
	@printf "$(GREEN)║   ✓ Setup complete!                   ║$(NC)\n"
	@printf "$(GREEN)╚════════════════════════════════════════╝$(NC)\n"
	@printf "\n"
	@printf "$(BLUE)Next steps:$(NC)\n"
	@printf "  1. Copy .env.example to .env and configure\n"
	@printf "  2. Run '$(GREEN)make docker-up$(NC)' to start full stack\n"
	@printf "\n"

## Info

info: ## Show project information
	@printf "$(BLUE)Project Information$(NC)\n"
	@printf "  Name: Watchdog HTTP\n"
	@printf "  Version: %s\n" "$$(grep '^version' pyproject.toml | cut -d'"' -f2)"
	@printf "  Python: %s\n" "$$(poetry run python --version)"
	@printf "\n"
	@printf "$(BLUE)Services$(NC)\n"
	@printf "  API: http://localhost:8000\n"
	@printf "  Docs: http://localhost:8000/docs\n"
	@printf "\n"
