Architecture
============

Overview
--------

The Autonomous ETL Agent is a cloud-native, LLM-driven system built on AWS ECS Fargate.
It separates concerns into two independently-scalable roles that share a single Docker image:

* **API service** — a FastAPI application that accepts user stories via REST, persists run
  state to PostgreSQL, and publishes pipeline jobs to an SQS queue.
* **Worker service** — a long-running SQS consumer that drives a LangGraph agentic pipeline
  to completion: parse → catalog lookup → code generation → testing → PR creation → deploy.

Both services run from the same ``python:3.12-slim`` Docker image. The worker simply
overrides the container ``CMD`` from ``uvicorn`` to ``python -m etl_agent.worker``.

.. mermaid::

   %%{init: {'theme': 'default', 'themeVariables': {'background': '#ffffff', 'mainBkg': '#ffffff', 'edgeLabelBackground': '#ffffff', 'nodeTextColor': '#000000'}}}%%
   flowchart TD
       Client(["🌐 Browser / curl"])
       ALB["🔀 Application Load Balancer\nHTTP :80"]
       API["⚡ FastAPI · uvicorn\nECS Fargate — API Service\n512 vCPU · 1 GB RAM · 1–4 tasks\nCPU autoscaling"]
       SQS[("📨 SQS Queue\netl-agent-pipeline\nvisibility=900s · DLQ after 3 retries")]
       Worker["🐍 Python · PySpark\nECS Fargate — Worker Service\n4 vCPU · 8 GB RAM · 0–10 tasks\nSQS-depth autoscaling"]
       LGLabel["LangGraph Pipeline"]
       PS["1️⃣ parse_story"]
       RC["2️⃣ resolve_catalog"]
       GC["3️⃣ generate_code"]
       RT["4️⃣ run_tests"]
       AG["5️⃣ approval_gate"]
       CP["6️⃣ create_pr"]
       D["7️⃣ deploy"]
       RDS[("🗄️ RDS PostgreSQL 16")]
       S3[("🪣 S3 × 3 Buckets")]
       Glue["🔍 Glue Data Catalog"]
       SM["🔐 Secrets Manager"]

       Client -->|"HTTP"| ALB
       ALB -->|"forward :8000"| API
       API -->|"SQS publish"| SQS
       SQS -->|"SQS consume"| Worker
       Worker -->|"drives"| LGLabel
       LGLabel --> PS
       PS --> RC --> GC --> RT --> AG --> CP --> D
       API ---|"reads/writes"| RDS
       Worker ---|"reads/writes"| RDS
       Worker ---|"artifacts"| S3
       Worker ---|"schema lookup"| Glue
       API ---|"secrets"| SM
       Worker ---|"secrets"| SM

   %% Light backgrounds, dark text, high-contrast borders
   classDef aws fill:#FFE0A0,color:#000,stroke:#CC7700,stroke-width:2px
   classDef ecs fill:#FFB3D9,color:#000,stroke:#B0004E,stroke-width:2px
   classDef data fill:#B7E1B0,color:#000,stroke:#2D6A2E,stroke-width:2px
   classDef lg fill:#B3D4FF,color:#000,stroke:#1A56BB,stroke-width:2px
   classDef lglabel fill:#E8F0FF,color:#000,stroke:#1A56BB,stroke-width:2px,stroke-dasharray:5 4
   class ALB,SM aws
   class API,Worker ecs
   class RDS,S3,Glue data
   class PS,RC,GC,RT,AG,CP,D lg
   class LGLabel lglabel


Key Design Decisions
--------------------

**Single image, two roles**
    The same Docker image runs both the API and the worker. This keeps the CI/CD pipeline
    simple (one build, one push) and ensures the code version is always consistent between
    the two roles. The worker's task definition overrides the container ``CMD``.

**SQS as the coordination layer**
    The API returns immediately with a ``run_id`` after publishing to SQS. The worker picks
    up the message asynchronously. This decouples request intake from execution, allows the
    worker to scale independently to zero, and provides automatic retry/DLQ handling for
    free.

**LangGraph for agent orchestration**
    LangGraph's ``StateGraph`` provides a deterministic DAG of agent nodes with typed shared
    state (``GraphState``). Each node is a standalone async function, making it easy to test
    nodes in isolation, add conditional edges (approval gate), and retry sub-graphs.

**Glue Data Catalog as the data model**
    Rather than hardcoding dataset schemas in the application, all knowledge about available
    datasets lives in the AWS Glue Data Catalog. A Glue Crawler scans the Olist S3 data
    on demand and registers table schemas. The ``StoryParserAgent`` queries the catalog at
    runtime to ground code generation in real column names.

**Immutable artifact delivery**
    Generated pipeline code is packaged as a Python ``.whl`` file, uploaded to a versioned
    S3 artifacts bucket, and referenced by a GitHub PR. This gives the team a reviewable,
    deployable artifact that is independent of the agent's runtime state.

Source Layout
-------------

.. code-block:: text

    autonomous-etl-agent/
    ├── src/etl_agent/
    │   ├── agents/          # Five LangGraph agent nodes
    │   │   ├── base.py      # ReactAgent base class (LLM loop + tool loop)
    │   │   ├── story_parser.py
    │   │   ├── coding_agent.py
    │   │   ├── test_agent.py
    │   │   ├── pr_agent.py
    │   │   └── deploy_agent.py
    │   ├── api/             # FastAPI application
    │   │   ├── main.py      # App factory, middleware, router registration
    │   │   ├── middleware.py # API key auth, request size limit
    │   │   └── v1/          # Versioned REST endpoints
    │   │       ├── stories.py   # POST /stories
    │   │       ├── runs.py      # GET /runs, GET /runs/{id}
    │   │       ├── catalog.py   # GET /catalog (Glue proxy)
    │   │       ├── health.py    # GET /health
    │   │       └── run_store.py # DB persistence helpers
    │   ├── core/
    │   │   ├── models.py    # Pydantic models: UserStory, ETLSpec, RunResult
    │   │   ├── state.py     # GraphState TypedDict + routing helpers
    │   │   ├── config.py    # Settings (pydantic-settings, .env)
    │   │   ├── data_catalog.py  # Glue boto3 client wrapper
    │   │   ├── audit.py     # Immutable audit event writer
    │   │   ├── llm_governance.py # Token budget tracker
    │   │   └── logging.py   # structlog configuration
    │   ├── database/
    │   │   ├── models.py    # SQLAlchemy ORM models
    │   │   ├── session.py   # Async session factory
    │   │   └── migrations/  # Alembic migrations
    │   ├── prompts/         # System + user prompt builders
    │   ├── tools/           # AWS, GitHub, code validator helpers
    │   ├── spark/           # PySpark session + optimizer helpers
    │   └── worker.py        # SQS consumer entry point
    ├── infra/
    │   ├── Dockerfile       # Multi-stage builder → runtime image
    │   ├── docker-compose.yml
    │   ├── ecs-task-def-api.json
    │   ├── ecs-task-def-worker.json
    │   └── terraform/       # All AWS infrastructure as code
    ├── tests/
    │   ├── unit/
    │   └── integration/
    └── .github/workflows/
        ├── ci.yml           # Lint, type-check, unit + integration tests
        └── cd.yml           # Build image, migrate DB, deploy to ECS
