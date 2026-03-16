# Setup Guide

## Prerequisites

- Python 3.12
- [UV](https://docs.astral.sh/uv/) installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Docker Desktop
- Git

## 1. Clone the Repository

```bash
git clone https://github.com/your-username/autonomous-etl-agent.git
cd autonomous-etl-agent
```

## 2. Install Dependencies

```bash
make install-dev
```

## 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | From [console.anthropic.com](https://console.anthropic.com) |
| `GITHUB_TOKEN` | ✅ | GitHub PAT with `repo`, `workflow`, `issues` scopes |
| `GITHUB_TARGET_REPO` | ✅ | e.g. `your-username/etl-pipelines-demo` |
| `AWS_ACCESS_KEY_ID` | ✅ | AWS credentials (use `test` for local dev) |
| `AWS_SECRET_ACCESS_KEY` | ✅ | AWS credentials (use `test` for local dev) |
| `API_KEY` | ✅ | Any secret string for API auth |
| `AWS_ENDPOINT_URL` | Local dev only | Set to `http://localstack:4566` |

## 4. Generate Test Fixtures

```bash
make generate-fixtures
```

## 5. Start All Services

```bash
make up
```

Services started:
- **ETL Agent API**: http://localhost:8000 (Swagger: http://localhost:8000/docs)
- **Airflow**: http://localhost:8080 (admin/admin)
- **LocalStack**: http://localhost:4566

## 6. Run the Demo

```bash
make demo
```

## 7. Run Tests

```bash
make test
```

## GitHub Actions Secrets

For CI/CD to work, add these secrets in your GitHub repo settings:

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `AWS_ACCESS_KEY_ID` | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials |
| `AWS_REGION` | e.g. `us-east-1` |
| `ECR_REGISTRY` | Your ECR registry URL |
| `EC2_HOST` | Your EC2 public IP/DNS |
| `EC2_SSH_KEY` | Private key for EC2 SSH |

## Cloud Deployment (Terraform)

```bash
make deploy
```

This provisions: S3 buckets, IAM roles, EC2 instance, ECR repository, security groups.
