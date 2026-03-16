# ⚡ Autonomous ETL Agent

> **Agentic AI Capstone Project** — Interview Kickstart · Transformative GenAI for Data Engineers

An AI-powered system that takes a plain-English DevOps user story (YAML), autonomously generates a production-ready PySpark ETL pipeline, writes and runs tests, creates a GitHub Issue + Pull Request, and optionally triggers Apache Airflow scheduling — all without human intervention.

---

## Architecture

```
User Story (YAML)
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LangGraph State Machine                       │
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ StoryParser  │───▶│ CodingAgent  │───▶│  TestAgent   │       │
│  │   Agent      │    │  (PySpark +  │    │  (pytest +   │       │
│  │  (Claude)    │    │  Delta Lake) │    │   coverage)  │       │
│  └──────────────┘    └──────────────┘    └──────┬───────┘       │
│                             ▲  retry on fail     │               │
│                             └────────────────────┘ pass          │
│                                                   │               │
│  ┌──────────────┐    ┌──────────────┐    ┌────────▼───────┐     │
│  │ DeployAgent  │◀───│   PRAgent    │◀───│ [Approval?]    │     │
│  │  (S3+Airflow)│    │  (GitHub)    │    │ (optional HiTL)│     │
│  └──────────────┘    └──────────────┘    └────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
   S3 Artifact          GitHub PR          Airflow DAG Run
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-20250514`) |
| **Agent Framework** | LangGraph + LangChain |
| **ETL Engine** | Apache PySpark 3.5 + Delta Lake |
| **API** | FastAPI + Uvicorn (async) |
| **Database** | SQLAlchemy 2.0 async + Alembic migrations |
| **Storage** | AWS S3 (LocalStack for local dev) |
| **Orchestration** | Apache Airflow 2.x (Celery executor) |
| **Git Automation** | PyGitHub |
| **Package Manager** | UV |
| **Logging** | structlog (JSON) |
| **Infrastructure** | Docker Compose + Terraform |
| **CI/CD** | GitHub Actions |

---

## Quick Start

### Prerequisites

- Python 3.12
- Java 17 (for PySpark)
- Docker + Docker Compose
- UV (`pip install uv`)

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/autonomous-etl-agent.git
cd autonomous-etl-agent

# Install all dependencies
make install-dev

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Configure `.env`

```bash
ANTHROPIC_API_KEY=sk-ant-...          # Required: Anthropic API key
GITHUB_TOKEN=ghp_...                  # Required: GitHub token (repo scope)
GITHUB_TARGET_REPO=your-org/etl-pipelines-demo  # Required: target repo for PRs
AWS_ACCESS_KEY_ID=test                # LocalStack: use "test"
AWS_SECRET_ACCESS_KEY=test            # LocalStack: use "test"
AWS_ENDPOINT_URL=http://localstack:4566  # LocalStack endpoint
API_KEY=your-secret-api-key           # Required: API auth key
```

### Run the Demo

```bash
# Start all services (Postgres, Redis, LocalStack, Airflow)
make up

# Generate sample data fixtures
make generate-fixtures

# Run the full agent demo (RFM analysis story)
make demo
```

### Use the CLI

```bash
# Run a user story
etl-agent run --story config/story_examples/rfm_analysis.yaml

# Dry run (no GitHub or Airflow calls)
etl-agent run --story config/story_examples/rfm_analysis.yaml --dry-run

# Start the REST API server
etl-agent serve
```

### Use the REST API

```bash
# Submit a user story
curl -X POST http://localhost:8000/api/v1/stories \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"story_yaml": "id: rfm_analysis\ntitle: RFM ...", "deploy": true}'

# Track the run
curl http://localhost:8000/api/v1/runs/<run_id> \
  -H "X-API-Key: your-api-key"

# Stream live logs (SSE)
curl http://localhost:8000/api/v1/runs/<run_id>/logs \
  -H "X-API-Key: your-api-key" \
  -H "Accept: text/event-stream"
```

### Use the Web UI

Navigate to `http://localhost:8000` after starting the services.

---

## Pipeline Run Flow

```
PENDING → PARSING → CODING → TESTING ──▶ AWAITING_APPROVAL (optional)
                                  │                │
                                  │ (retry x2)     │
                                  ◀────────────────┘ approved
                                        │
                                  PR_CREATING → DEPLOYING → DONE
```

---

## Project Structure

```
autonomous-etl-agent/
├── src/etl_agent/
│   ├── agents/              # LangGraph agent nodes
│   │   ├── orchestrator.py  # LangGraph graph builder + run_pipeline()
│   │   ├── story_parser.py  # Parses YAML → ETLSpec
│   │   ├── coding_agent.py  # Generates PySpark code (Claude)
│   │   ├── test_agent.py    # Generates + runs pytest tests
│   │   ├── pr_agent.py      # Creates GitHub Issue + PR
│   │   └── deploy_agent.py  # Packages .whl, uploads S3, triggers Airflow
│   ├── api/                 # FastAPI application
│   │   ├── main.py          # App factory, lifespan, CORS
│   │   ├── middleware.py     # API key authentication
│   │   └── v1/              # Versioned routes (health, stories, runs)
│   ├── analytics/           # Business analytics pipelines
│   │   ├── rfm_analysis.py
│   │   ├── geo_analytics.py
│   │   ├── campaign_optimizer.py
│   │   └── customer_intent.py
│   ├── core/                # Shared models, config, state, exceptions
│   ├── database/            # SQLAlchemy models, session, Alembic migrations
│   ├── prompts/             # LLM prompt templates + few-shot examples
│   ├── spark/               # Spark session, optimizer, Jinja2 templates
│   ├── tools/               # GitHub, AWS, code validation utilities
│   └── ui/                  # Web UI (HTML templates + JS)
├── config/
│   ├── framework_config.yaml
│   └── story_examples/      # 6 example user stories (YAML)
├── infra/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── postgres-init.sql
│   └── terraform/           # EC2, ECR, S3, IAM, Security Groups
├── orchestration/
│   └── airflow/dags/        # etl_agent_pipeline DAG
├── scripts/
│   ├── demo_run.py
│   ├── generate_fixtures.py
│   └── seed_db.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── notebooks/educational/   # Jupyter notebooks for learning
├── docs/                    # API, config guide, setup, runbook
├── .github/workflows/       # CI (lint+test) + CD (build+deploy)
├── pyproject.toml           # UV project config
├── Makefile
└── .env.example
```

---

## Story Examples

Six ready-to-use user stories are included in `config/story_examples/`:

| File | Description |
|------|-------------|
| `rfm_analysis.yaml` | RFM customer segmentation with quintile bucketing |
| `geo_analytics.yaml` | Geographic revenue analytics with broadcast join |
| `campaign_performance.yaml` | iPhone 17 marketing campaign KPI optimizer |
| `monthly_revenue.yaml` | Monthly revenue aggregation by category |
| `join_aggregate.yaml` | Order line enrichment and monthly aggregation |
| `clean_nulls.yaml` | Data quality pipeline with null handling |

---

## Running Tests

```bash
make test              # All tests
make test-unit         # Unit tests only (fast)
make test-integration  # Integration tests (needs services)
make lint              # Ruff linting
make typecheck         # mypy type checking
make format            # Auto-format code
```

---

## Cloud Deployment

```bash
# Preview Terraform plan
make deploy-plan

# Deploy to AWS (EC2 + ECR + S3 + IAM)
make deploy

# Destroy all cloud resources
make deploy-destroy
```

See `docs/setup.md` for the full deployment guide.

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/setup.md`](docs/setup.md) | Full installation and deployment guide |
| [`docs/api.md`](docs/api.md) | REST API reference |
| [`docs/config_guide.md`](docs/config_guide.md) | User story format + framework config |
| [`docs/architecture.md`](docs/architecture.md) | Architecture diagrams and design decisions |
| [`docs/runbook.md`](docs/runbook.md) | Operations, monitoring, incident response |

---

## Grading Rubric Coverage

| Requirement | Implementation |
|-------------|---------------|
| Multi-agent LLM pipeline | LangGraph with 5 specialized agents |
| ETL code generation | CodingAgent → PySpark 3.5 + Delta Lake |
| Automated testing | TestAgent → pytest + coverage measurement |
| GitHub integration | PRAgent → Issue + Branch + Commit + PR |
| Cloud storage | DeployAgent → S3 artifact upload |
| Workflow orchestration | DeployAgent → Airflow REST API trigger |
| Human-in-the-loop | `REQUIRE_HUMAN_APPROVAL` flag + approval endpoint |
| Retry mechanism | LangGraph conditional edge with `max_retries` |
| Structured logging | structlog JSON logging |
| Production API | FastAPI + API key auth + rate limiting + SSE |
| Infrastructure as Code | Terraform (EC2, ECR, S3, IAM, Security Group) |
| CI/CD | GitHub Actions (lint + test + build + deploy) |
| Business analytics | RFM, Geo, Campaign, Customer Intent pipelines |

---

## License

MIT License — see `LICENSE` file.

---

*Built with ❤️ for the Interview Kickstart Agentic AI / Transformative GenAI for Data Engineers capstone.*
