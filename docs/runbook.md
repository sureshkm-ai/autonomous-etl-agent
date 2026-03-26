# Operations Runbook

This runbook covers day-to-day operations, incident response, and security considerations for the Autonomous ETL Agent.

---

## Service Architecture Overview

```
Internet / CI
    │
    ▼
[ EC2 (Docker) ] ──── ETL Agent App (FastAPI :8000)
    │                        │
    │                        ├── LangGraph (5 agents)
    │                        │     └── Anthropic Claude API
    │                        ├── SQLite / PostgreSQL
    │                        └── boto3 → S3
    │
    ├── LocalStack :4566 (local dev only)
    ├── Airflow Webserver :8080
    ├── Airflow Scheduler
    ├── Airflow Celery Worker
    ├── Redis :6379 (Celery broker)
    └── PostgreSQL :5432 (Airflow + ETL Agent metadata)
```

---

## Starting and Stopping Services

```bash
# Start all services
make up

# Stop all services (keep volumes)
make down

# Restart a single service
docker compose -f infra/docker-compose.yml restart app

# Follow logs
make logs

# Follow a single service's logs
docker compose -f infra/docker-compose.yml logs -f app
```

---

## Database Operations

### Run Migrations

```bash
# Apply all pending migrations
make migrate

# Rollback one migration
make migrate-down

# Check current migration head
docker compose -f infra/docker-compose.yml exec app \
  alembic -c src/etl_agent/database/migrations/alembic.ini current
```

### Seed Demo Data

```bash
make seed-db
```

### Connect to PostgreSQL

```bash
docker compose -f infra/docker-compose.yml exec postgres \
  psql -U etl_user -d etl_agent
```

---

## Running Tests

```bash
# Full test suite
make test

# Unit tests only (fast, no external services)
make test-unit

# Integration tests (requires Docker services running)
make test-integration

# Test with coverage report
uv run pytest --cov=etl_agent --cov-report=html tests/
open htmlcov/index.html
```

Minimum required coverage: **80%**. The CI pipeline will fail if coverage drops below this threshold.

---

## Monitoring

### Health Check

```bash
curl http://localhost:8000/api/v1/health
# Expected: {"status": "ok", "version": "1.0.0"}
```

### Check Running Pipelines

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/runs?status=CODING
```

### Stream Live Logs

```bash
curl -H "X-API-Key: $API_KEY" \
     -H "Accept: text/event-stream" \
     http://localhost:8000/api/v1/runs/<run_id>/logs
```

### Airflow UI

Navigate to `http://localhost:8080` (admin / admin) to view DAG runs triggered by the Deploy Agent.

### LocalStack Dashboard

```bash
# Check service health
curl http://localhost:4566/_localstack/health

# List S3 buckets
aws --endpoint-url=http://localhost:4566 s3 ls

# List pipeline artifacts
aws --endpoint-url=http://localhost:4566 s3 ls s3://etl-agent-artifacts/ --recursive
```

---

## Incident Response

### Pipeline Stuck in CODING / TESTING

1. Check app logs: `docker compose logs app | grep ERROR`
2. Verify Anthropic API key is valid: `curl https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY"`
3. Check if max retries was exhausted: `GET /runs/<run_id>` → look at `retry_count` and `error_message`
4. If the story YAML is malformed, fix it and resubmit via `POST /stories`

### GitHub PR Creation Failing

1. Verify token: `curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user`
2. Check repo permissions: token must have `repo` scope
3. Verify `GITHUB_TARGET_REPO` is correct (format: `owner/repo`)
4. Look for branch name conflicts: `GET /runs/<run_id>` → `github_branch_name`

### S3 Upload Failing

1. Check LocalStack is healthy: `curl http://localhost:4566/_localstack/health`
2. Verify bucket exists: `aws --endpoint-url=http://localhost:4566 s3 ls`
3. For production: check IAM role has `s3:PutObject` on `aws_s3_artifacts_bucket`
4. Note: S3/Airflow failure does NOT mark the run as FAILED — check `airflow_dag_run_id` is null

### Airflow Trigger Not Working

1. Verify Airflow is up: `curl http://localhost:8080/health`
2. Check the DAG exists and is unpaused in the Airflow UI
3. Verify credentials: `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD`
4. Check the `etl_agent_pipeline` DAG is not paused (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=true`)

### Database Connection Errors

1. Check PostgreSQL is healthy: `docker compose ps postgres`
2. Run: `docker compose logs postgres | tail -50`
3. Verify connection string in `.env` matches `infra/docker-compose.yml`
4. Restart: `docker compose -f infra/docker-compose.yml restart postgres`

---

## Log Analysis

Logs are structured JSON (structlog). Use `jq` for filtering:

```bash
# Show all ERROR-level events
docker compose logs app 2>&1 | grep '"level":"error"' | jq .

# Filter by run_id
docker compose logs app 2>&1 | jq '. | select(.run_id == "<run_id>")'

# Show all agent events
docker compose logs app 2>&1 | jq '. | select(.event | startswith("["))'
```

---

## Backup and Recovery

### Backup PostgreSQL

```bash
docker compose -f infra/docker-compose.yml exec postgres \
  pg_dump -U etl_user etl_agent > backup_$(date +%Y%m%d).sql
```

### Restore PostgreSQL

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U etl_user etl_agent < backup_20250101.sql
```

### Backup S3 Artifacts (LocalStack)

```bash
aws --endpoint-url=http://localhost:4566 s3 sync \
  s3://etl-agent-artifacts ./artifacts-backup/
```

---

## Security

### Secret Management

**Never commit secrets to version control.** The `.gitignore` excludes `.env`, but stay vigilant.

All secrets are loaded from environment variables. The `.env.example` file shows required variables without real values. Use a secrets manager (AWS Secrets Manager, HashiCorp Vault) in production.

The pre-commit hook `detect-private-key` will block commits that accidentally include private keys or API tokens.

### API Key Rotation

1. Generate a new key: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update `API_KEY` in `.env` and redeploy
3. Update `API_KEY` secret in GitHub Actions secrets

### GitHub Token Scopes

The `GITHUB_TOKEN` requires the following scopes:
- `repo` — create issues, branches, commits, PRs
- `workflow` *(optional)* — trigger GitHub Actions

Use a fine-grained token scoped to the target repository only for least-privilege access.

### AWS IAM Least Privilege

The Terraform IAM policy (`infra/terraform/iam.tf`) grants the EC2 instance only:
- `s3:PutObject` on the artifacts bucket
- `s3:GetObject` on the artifacts bucket
- `s3:ListBucket` on the artifacts bucket

No other AWS services are accessible from the instance role.

### Network Security

The Security Group (`infra/terraform/security_group.tf`) allows inbound traffic only on:
- Port 80 / 443 (HTTP/HTTPS)
- Port 8000 (ETL Agent API)
- Port 22 (SSH — restrict to your IP in production)

All other ports are blocked. Redis and PostgreSQL are not exposed to the internet.

### Docker Container Security

- The application runs as non-root user `etlagent` (UID 1000)
- The container image is based on `python:3.12-slim` (minimal attack surface)
- No `--privileged` flag is used
- Secrets are mounted via environment variables, not baked into the image

---

## Terraform Operations

```bash
# Preview infrastructure changes
make deploy-plan

# Apply infrastructure changes
make deploy

# Tear down all cloud resources
make deploy-destroy
```

### Terraform State

Terraform state is stored locally in `infra/terraform/terraform.tfstate`. In production, migrate state to an S3 backend:

```hcl
# Add to infra/terraform/main.tf
terraform {
  backend "s3" {
    bucket = "my-terraform-state"
    key    = "etl-agent/terraform.tfstate"
    region = "us-east-1"
  }
}
```

---

## CI/CD Pipeline

### GitHub Actions Workflows

| Workflow | Trigger | Jobs |
|----------|---------|------|
| `ci.yml` | Push / PR to `main` | lint → typecheck → test-unit → test-integration |
| `cd.yml` | Push to `main` (after CI passes) | build-push-ECR → deploy-EC2 → smoke-test |

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | For integration tests |
| `GITHUB_TOKEN` | Auto-provided by Actions |
| `AWS_ACCESS_KEY_ID` | ECR push + S3 access |
| `AWS_SECRET_ACCESS_KEY` | ECR push + S3 access |
| `EC2_HOST` | EC2 public IP or DNS |
| `EC2_SSH_KEY` | Private key for SSH deployment |
| `API_KEY` | ETL Agent API key for smoke test |

---

## Performance Tuning

### Spark Memory

If PySpark OOM errors occur, increase driver/executor memory in `src/etl_agent/spark/session.py`:

```python
.config("spark.driver.memory", "4g")
.config("spark.executor.memory", "4g")
```

### LLM Cache

For development, the agent caches LLM responses in SQLite (`llm_cache.db`). This dramatically reduces API costs during repeated testing. In production, responses are cached in Redis.

To clear the cache: `rm llm_cache.db` or flush Redis: `redis-cli FLUSHDB`.

### Retry Configuration

If the LLM generates failing code frequently, increase `MAX_RETRIES` in `.env` (default: 2). Each retry sends test failure details back to the LLM for correction.
