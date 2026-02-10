.PHONY: help install dev test lint format clean docker-up docker-down docker-build migrate upgrade downgrade pre-commit sync-version

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Watchdog HTTP - Available Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

## Development Environment

install: ## Install dependencies with Poetry
	@echo "$(BLUE)Installing dependencies...$(NC)"
	cd src && poetry install
	cd ui && poetry install
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

dev: ## Run development server with auto-reload
	@echo "$(BLUE)Starting development server...$(NC)"
	cd src && poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run ARQ worker for background tasks
	@echo "$(BLUE)Starting ARQ worker...$(NC)"
	cd src && poetry run arq src.worker.main.WorkerSettings

ui: ## Run Streamlit UI dashboard
	@echo "$(BLUE)Starting Streamlit UI...$(NC)"
	cd ui && poetry run streamlit run app.py

## Code Quality

lint: ## Run linters (mypy type checking)
	@echo "$(BLUE)Running type checks...$(NC)"
	cd src && poetry run mypy .
	@echo "$(GREEN)✓ Lint complete$(NC)"

format: ## Format code with black
	@echo "$(BLUE)Formatting code...$(NC)"
	cd src && poetry run black .
	cd ui && poetry run black .
	@echo "$(GREEN)✓ Code formatted$(NC)"

# test: ## Run tests with pytest
#	@echo "$(BLUE)Running tests...$(NC)"
#	cd src && poetry run pytest -v
#	@echo "$(GREEN)✓ Tests complete$(NC)"

check: format lint ## Run all checks (format + lint)
	@echo "$(GREEN)✓ All checks passed$(NC)"

## Database

migrate: ## Create a new migration
	@echo "$(BLUE)Creating new migration...$(NC)"
	@read -p "Migration message: " msg; \
	cd src && poetry run alembic revision --autogenerate -m "$$msg"
	@echo "$(GREEN)✓ Migration created$(NC)"

upgrade: ## Upgrade database to latest migration
	@echo "$(BLUE)Upgrading database...$(NC)"
	cd src && poetry run alembic upgrade head
	@echo "$(GREEN)✓ Database upgraded$(NC)"

downgrade: ## Downgrade database by one revision
	@echo "$(BLUE)Downgrading database...$(NC)"
	cd src && poetry run alembic downgrade -1
	@echo "$(GREEN)✓ Database downgraded$(NC)"

db-reset: ## Reset database (downgrade all + upgrade head)
	@echo "$(YELLOW)⚠ This will reset the database!$(NC)"
	@read -p "Are you sure? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		cd src && poetry run alembic downgrade base && poetry run alembic upgrade head; \
		echo "$(GREEN)✓ Database reset complete$(NC)"; \
	else \
		echo "$(RED)Aborted$(NC)"; \
	fi

## Docker

docker-build: ## Build Docker images
	@echo "$(BLUE)Building Docker images...$(NC)"
	docker-compose build
	@echo "$(GREEN)✓ Docker images built$(NC)"

docker-up: ## Start all services with Docker Compose
	@echo "$(BLUE)Starting Docker services...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Services started$(NC)"
	@echo "API: http://localhost:8000"
	@echo "UI: http://localhost:8501"

docker-down: ## Stop all Docker services
	@echo "$(BLUE)Stopping Docker services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Services stopped$(NC)"

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
		echo "$(GREEN)✓ Cleanup complete$(NC)"; \
	else \
		echo "$(RED)Aborted$(NC)"; \
	fi

## Git & Version Management

pre-commit: ## Install pre-commit hooks
	@echo "$(BLUE)Installing pre-commit hooks...$(NC)"
	@if ! command -v pre-commit &> /dev/null; then \
		echo "$(YELLOW)pre-commit not found. Installing...$(NC)"; \
		pip install pre-commit; \
	fi
	pre-commit install
	@echo "$(GREEN)✓ Pre-commit hooks installed$(NC)"

pre-commit-run: ## Run pre-commit on all files
	@echo "$(BLUE)Running pre-commit hooks...$(NC)"
	pre-commit run --all-files
	@echo "$(GREEN)✓ Pre-commit checks complete$(NC)"

sync-version: ## Sync version across all files (usage: make sync-version VERSION=1.6.0)
	@echo "$(BLUE)Syncing version across files...$(NC)"
	@if [ -z "$(VERSION)" ]; then \
		echo "$(RED)Error: VERSION is required$(NC)"; \
		echo "Usage: make sync-version VERSION=1.6.0"; \
		exit 1; \
	fi
	@python scripts/sync_version.py $(VERSION)
	@echo "$(GREEN)✓ Version synced$(NC)"

## Cleanup

clean: ## Clean temporary files and caches
	@echo "$(BLUE)Cleaning temporary files...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*~" -delete 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-logs: ## Remove log files
	@echo "$(BLUE)Removing log files...$(NC)"
	rm -f logs/*.json
	@echo "$(GREEN)✓ Logs cleaned$(NC)"

## Complete Setup

setup: install pre-commit upgrade ## Complete setup (install + pre-commit + migrations)
	@echo ""
	@echo "$(GREEN)╔════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║   ✓ Setup complete!                   ║$(NC)"
	@echo "$(GREEN)╚════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(BLUE)Next steps:$(NC)"
	@echo "  1. Copy .env.example to .env and configure"
	@echo "  2. Run '$(GREEN)make dev$(NC)' to start development server"
	@echo "  3. Run '$(GREEN)make worker$(NC)' to start background worker"
	@echo ""

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
