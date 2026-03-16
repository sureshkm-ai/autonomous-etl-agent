# Architecture — Autonomous ETL Agent

## System Overview

The Autonomous ETL Agent is a multi-agent AI system that transforms DevOps user stories
into production-ready PySpark pipelines, tests, and Pull Requests — autonomously.

## Agent Pipeline (LangGraph State Machine)

```mermaid
graph TD
    A[User Story YAML] --> B[Story Parser Agent]
    B -->|ETLSpec| C[Coding Agent]
    C -->|PySpark code + README| D[Test Agent]
    D -->|Tests pass| E{Human Approval?}
    D -->|Tests fail, retries left| C
    D -->|Max retries exceeded| F[Failure Handler]
    E -->|Approved / disabled| G[PR Agent]
    E -->|Waiting| E
    G -->|PR created| H[Deploy Agent]
    G -->|PR failed| F
    H -->|.whl → S3 → Airflow| I[✅ DONE]
    F --> J[❌ FAILED]
```

## Component Diagram

```mermaid
graph LR
    subgraph "Client Layer"
        UI[Web UI<br/>story intake / run monitoring]
        CLI[CLI<br/>etl-agent run]
    end

    subgraph "API Layer"
        API[FastAPI /api/v1<br/>stories · runs · health]
        MW[Middleware<br/>API Key Auth · Rate Limit]
    end

    subgraph "Agent Layer"
        ORCH[LangGraph Orchestrator]
        SP[Story Parser]
        CA[Coding Agent]
        TA[Test Agent]
        PRA[PR Agent]
        DA[Deploy Agent]
    end

    subgraph "Intelligence"
        LLM[Claude Sonnet 4.6<br/>Anthropic API]
        CACHE[LLM Cache<br/>SQLite dev / Redis prod]
    end

    subgraph "External Services"
        GH[GitHub<br/>Issues · PRs]
        S3[AWS S3<br/>raw / processed / artifacts]
        AF[Apache Airflow<br/>DAG scheduling]
    end

    subgraph "Data Store"
        DB[(PostgreSQL<br/>SQLAlchemy ORM)]
        DELTA[Delta Lake<br/>table management]
    end

    UI --> API
    CLI --> ORCH
    API --> ORCH
    ORCH --> SP & CA & TA & PRA & DA
    SP & CA & TA & PRA --> LLM
    LLM --> CACHE
    PRA --> GH
    DA --> S3
    DA --> AF
    API --> DB
    CA & TA --> DELTA
```

## Technology Choices & Rationale

| Component | Choice | Rationale |
|---|---|---|
| LLM | Claude Sonnet 4.6 | Best structured output quality, long context |
| Agent Framework | LangGraph | Stateful, conditional edges, retry loops |
| ETL Engine | PySpark 3.5 + Delta Lake | Industry standard; ACID on data lakes |
| API | FastAPI + Uvicorn | Async, auto-docs, Pydantic integration |
| Database | SQLAlchemy 2.0 async | Type-safe ORM, async sessions |
| Storage | AWS S3 | Industry standard object store |
| Orchestration | Apache Airflow | Widely adopted, REST API triggerable |
| Package Manager | UV | Fastest Python package manager |
| IaC | Terraform | Reproducible cloud infrastructure |
