# ═══════════════════════════════════════════════════════════════════════════════
# Autonomous ETL Agent — Makefile
# ═══════════════════════════════════════════════════════════════════════════════

.DEFAULT_GOAL := help
export PYTHONPATH := src

# ── Colours ───────────────────────────────────────────────────────────────────
CYAN  := \033[0;36m
RESET := \033[0m

.PHONY: help install install-dev test test-unit test-integration lint format \
        typecheck pre-commit demo up down localstack-up localstack-down migrate \
        generate-fixtures seed-db deploy clean build

help: ## Show this help message
	@echo "$(CYAN)Autonomous ETL Agent$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'

# ── Installation ──────────────────────────────────────────────────────────────
install: ## Install production dependencies via UV
	uv sync --no-dev
	@echo "✅ Production dependencies installed"

install-dev: ## Install all dependencies including dev tools
	uv sync
	uv run pre-commit install
	@echo "✅ Dev dependencies installed + pre-commit hooks set up"

# ── Java 17 detection (PySpark 3.5 / Hadoop 3.3.x is incompatible with Java 21)
# Prefer brew-installed Java 17; fall back to Linux paths; fall back to JAVA_HOME as-is.
JAVA17_HOME := $(shell \
  for p in \
    "$$(brew --prefix openjdk@17 2>/dev/null)/libexec/openjdk.jdk/Contents/Home" \
    "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" \
    "/usr/lib/jvm/java-17-openjdk-arm64" \
    "/usr/lib/jvm/java-17-openjdk-amd64" \
    "/usr/lib/jvm/java-17-openjdk" \
    "/usr/lib/jvm/temurin-17"; \
  do [ -d "$$p" ] && echo "$$p" && break; done)

# Only override JAVA_HOME when we actually found a Java 17 installation
JAVA_HOME_SET := $(if $(JAVA17_HOME),JAVA_HOME="$(JAVA17_HOME)",)

# ── Testing ───────────────────────────────────────────────────────────────────
test: ## Run all tests with coverage
	$(JAVA_HOME_SET) uv run pytest tests/ -v

test-unit: ## Run unit tests only (fast)
	$(JAVA_HOME_SET) uv run pytest tests/unit/ -v

test-integration: ## Run integration tests (requires LocalStack: make localstack-up)
	$(JAVA_HOME_SET) uv run pytest tests/integration/ -v

# ── Code Quality ──────────────────────────────────────────────────────────────
lint: ## Run ruff linter
	uv run ruff check src/ tests/

format: ## Auto-format code with ruff
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

typecheck: ## Run mypy type checker
	uv run mypy src/

pre-commit: ## Run all pre-commit hooks against all files
	uv run pre-commit run --all-files

# ── Database ──────────────────────────────────────────────────────────────────
migrate: ## Run Alembic migrations (upgrade to head)
	uv run alembic -c src/etl_agent/database/migrations/alembic.ini upgrade head

migrate-down: ## Rollback last migration
	uv run alembic -c src/etl_agent/database/migrations/alembic.ini downgrade -1

# ── Data Fixtures ─────────────────────────────────────────────────────────────
generate-fixtures: ## Generate Amazon Parquet fixture files for tests/demo
	uv run python scripts/generate_fixtures.py
	@echo "✅ Parquet fixtures written to tests/fixtures/data/"

seed-db: ## Seed database with demo pipeline runs
	uv run python scripts/seed_db.py
	@echo "✅ Database seeded"

# ── Docker ────────────────────────────────────────────────────────────────────
up: ## Start all services via docker-compose (dev mode)
	docker compose -f infra/docker-compose.yml up -d
	@echo "✅ Services started. App: http://localhost:8000 | Airflow: http://localhost:8080"

down: ## Stop all services
	docker compose -f infra/docker-compose.yml down

logs: ## Tail app logs
	docker compose -f infra/docker-compose.yml logs -f app

localstack-up: ## Start LocalStack only (S3 for integration tests)
	docker compose -f infra/docker-compose.yml up -d localstack
	@echo "✅ LocalStack started at http://localhost:4566"

localstack-down: ## Stop LocalStack
	docker compose -f infra/docker-compose.yml stop localstack

# ── Demo ──────────────────────────────────────────────────────────────────────
demo: ## Run full E2E demo (story → code → tests → PR)
	@echo "$(CYAN)Running Autonomous ETL Agent demo...$(RESET)"
	uv run python scripts/demo_run.py

# ── Build ─────────────────────────────────────────────────────────────────────
build: ## Build production Docker image
	docker build -f infra/Dockerfile -t etl-agent:latest .

# ── Cloud Deploy ──────────────────────────────────────────────────────────────
deploy: ## Deploy infrastructure via Terraform
	cd infra/terraform && terraform init && terraform apply -auto-approve

deploy-plan: ## Preview Terraform changes without applying
	cd infra/terraform && terraform init && terraform plan

deploy-destroy: ## Destroy all cloud infrastructure (DANGEROUS)
	cd infra/terraform && terraform destroy

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean: ## Remove all build artifacts, caches, and generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	rm -rf dist/ build/ *.egg-info
	rm -f etl_agent.db
	@echo "✅ Clean complete"
