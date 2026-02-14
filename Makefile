.PHONY: help install dev test lint format clean docker-up docker-down docker-build migrate upgrade downgrade pre-commit sync-version

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
	cd src && poetry install
	cd ui && poetry install
	@printf "$(GREEN)✓ Dependencies installed$(NC)\n"

dev: ## Run development server with auto-reload
	@printf "$(BLUE)Starting development server...$(NC)\n"
	cd src && poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run ARQ worker for background tasks
	@printf "$(BLUE)Starting ARQ worker...$(NC)\n"
	cd src && poetry run arq src.worker.main.WorkerSettings

ui: ## Run Streamlit UI dashboard
	@printf "$(BLUE)Starting Streamlit UI...$(NC)\n"
	cd ui && poetry run streamlit run app.py

## Code Quality

lint: ## Run linters (mypy type checking)
	@printf "$(BLUE)Running type checks...$(NC)\n"
	cd src && poetry run mypy .
	@printf "$(GREEN)✓ Lint complete$(NC)\n"

format: ## Format code with black
	@printf "$(BLUE)Formatting code...$(NC)\n"
	cd src && poetry run black .
	cd ui && poetry run black .
	@printf "$(GREEN)✓ Code formatted$(NC)\n"

# test: ## Run tests with pytest
#	@echo "$(BLUE)Running tests...$(NC)"
#	cd src && poetry run pytest -v
#	@echo "$(GREEN)✓ Tests complete$(NC)"

check: format lint ## Run all checks (format + lint)
	@printf "$(GREEN)✓ All checks passed$(NC)\n"

## Database

migrate: ## Create a new migration
	@printf "$(BLUE)Creating new migration...$(NC)\n"
	@read -p "Migration message: " msg; \
	cd src && PYTHONPATH=.. poetry run alembic revision --autogenerate -m "$$msg"
	@printf "$(GREEN)✓ Migration created$(NC)\n"

upgrade: ## Upgrade database to latest migration
	@printf "$(BLUE)Upgrading database...$(NC)\n"
	cd src && PYTHONPATH=.. poetry run alembic upgrade head
	@printf "$(GREEN)✓ Database upgraded$(NC)\n"

downgrade: ## Downgrade database by one revision
	@printf "$(BLUE)Downgrading database...$(NC)\n"
	cd src && PYTHONPATH=.. poetry run alembic downgrade -1
	@printf "$(GREEN)✓ Database downgraded$(NC)\n"

db-reset: ## Reset database (downgrade all + upgrade head)
	@printf "$(YELLOW)⚠ This will reset the database!$(NC)\n"
	@read -p "Are you sure? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		cd src && PYTHONPATH=.. poetry run alembic downgrade base && PYTHONPATH=.. poetry run alembic upgrade head; \
		printf "$(GREEN)✓ Database reset complete$(NC)\n"; \
	else \
		printf "$(RED)Aborted$(NC)\n"; \
	fi

## Docker

docker-build: ## Build Docker images
	@printf "$(BLUE)Building Docker images...$(NC)\n"
	docker-compose build
	@printf "$(GREEN)✓ Docker images built$(NC)\n"

docker-up: ## Start all services with Docker Compose
	@printf "$(BLUE)Starting Docker services...$(NC)\n"
	docker-compose up -d
	@printf "$(GREEN)✓ Services started$(NC)\n"
	@printf "API: http://localhost:8000\n"
	@printf "UI: http://localhost:8501\n"

docker-down: ## Stop all Docker services
	@printf "$(BLUE)Stopping Docker services...$(NC)\n"
	docker-compose down
	@printf "$(GREEN)✓ Services stopped$(NC)\n"

docker-logs: ## Show Docker logs (use service=<name> for specific service)
	@if [ -z "$(service)" ]; then \
		docker-compose logs -f; \
	else \
		docker-compose logs -f $(service); \
	fi

docker-restart: docker-down docker-up ## Restart all Docker services

docker-clean: ## Remove all containers, volumes and images
	@echo "$(YELLOW)⚠ This will remove all containers, volumes and images!$(NC)"
	@read -p "Are you sure? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		docker-compose down -v --rmi all; \
		printf "$(GREEN)✓ Cleanup complete$(NC)\n"; \
	else \
		printf "$(RED)Aborted$(NC)\n"; \
	fi

## Git & Version Management

pre-commit: ## Install pre-commit hooks
	@printf "$(BLUE)Installing pre-commit hooks...$(NC)\n"
	@if ! command -v pre-commit &> /dev/null; then \
		printf "$(YELLOW)pre-commit not found. Installing...$(NC)\n"; \
		pip install pre-commit; \
	fi
	pre-commit install
	@printf "$(GREEN)✓ Pre-commit hooks installed$(NC)\n"

pre-commit-run: ## Run pre-commit on all files
	@printf "$(BLUE)Running pre-commit hooks...$(NC)\n"
	pre-commit run --all-files
	@printf "$(GREEN)✓ Pre-commit checks complete$(NC)\n"

sync-version: ## Sync version across all files (usage: make sync-version VERSION=1.6.0)
	@printf "$(BLUE)Syncing version across files...$(NC)\n"
	@if [ -z "$(VERSION)" ]; then \
		printf "$(RED)Error: VERSION is required$(NC)\n"; \
		printf "Usage: make sync-version VERSION=1.6.0\n"; \
		exit 1; \
	fi
	@python scripts/sync_version.py $(VERSION)
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
	@printf "  2. Run '$(GREEN)make dev$(NC)' to start development server\n"
	@printf "  3. Run '$(GREEN)make worker$(NC)' to start background worker\n"
	@printf "\n"

## Info

info: ## Show project information
	@printf "$(BLUE)Project Information$(NC)\n"
	@printf "  Name: Watchdog HTTP\n"
	@printf "  Version: %s\n" "$$(grep '^version' src/pyproject.toml | cut -d'"' -f2)"
	@printf "  Python: %s\n" "$$(cd src && poetry run python --version)"
	@printf "\n"
	@printf "$(BLUE)Services$(NC)\n"
	@printf "  API: http://localhost:8000\n"
	@printf "  Docs: http://localhost:8000/docs\n"
	@printf "  UI: http://localhost:8501\n"
	@printf "\n"
