Getting Started (Local Development)
====================================

Prerequisites
-------------

Ensure the following tools are installed on your machine:

* Python 3.12 (``pyenv`` recommended)
* ``uv`` — fast Python package manager (``pip install uv``)
* Docker Desktop with Compose V2
* AWS CLI v2 (configured with credentials)
* Git

Optional but recommended:

* ``pre-commit`` (``pip install pre-commit``)

Clone the Repository
--------------------

.. code-block:: bash

    git clone https://github.com/<your-org>/autonomous-etl-agent.git
    cd autonomous-etl-agent

Configure Environment
---------------------

.. code-block:: bash

    cp .env.example .env

Open ``.env`` and fill in the required values:

.. code-block:: bash

    # Required for LLM calls
    ANTHROPIC_API_KEY=sk-ant-...

    # GitHub Personal Access Token (needs: repo, workflow, issues)
    GITHUB_TOKEN=ghp_...
    GITHUB_TARGET_REPO=your-username/etl-pipelines    # where PRs are created

    # AWS credentials (LocalStack is used locally — real credentials still needed
    # for the CLI, but LocalStack accepts any value for the key/secret)
    AWS_ACCESS_KEY_ID=test
    AWS_SECRET_ACCESS_KEY=test
    AWS_REGION=us-east-1
    AWS_ENDPOINT_URL=http://localstack:4566           # points to LocalStack

    # Leave as SQLite for local dev
    DATABASE_URL=sqlite+aiosqlite:///./etl_agent.db

    # API authentication key (choose any string)
    API_KEY=my-local-dev-key

Install Python Dependencies
---------------------------

.. code-block:: bash

    uv sync

This installs all dependencies (including dev tools) from ``uv.lock`` into a
``.venv`` directory.

Activate the virtual environment:

.. code-block:: bash

    source .venv/bin/activate    # macOS / Linux
    .venv\Scripts\activate       # Windows

Set Up Pre-commit Hooks
-----------------------

.. code-block:: bash

    pre-commit install

This sets up ruff (lint + format), mypy, and other hooks to run on every commit.

Start the Local Stack
---------------------

.. code-block:: bash

    docker compose -f infra/docker-compose.yml up -d

This starts PostgreSQL, Redis, LocalStack, the FastAPI app, and Airflow.
Wait until all services are healthy (roughly 60 seconds):

.. code-block:: bash

    docker compose -f infra/docker-compose.yml ps

All services should show ``healthy``.

Run Database Migrations
-----------------------

.. code-block:: bash

    uv run alembic -c src/etl_agent/database/migrations/alembic.ini upgrade head

Run the Application Without Docker
------------------------------------

For faster development iteration, run the FastAPI app directly:

.. code-block:: bash

    uv run uvicorn etl_agent.api.main:app --reload --port 8000

The API is available at ``http://localhost:8000``.
The Swagger UI is at ``http://localhost:8000/docs``.

Verify the Setup
----------------

.. code-block:: bash

    curl http://localhost:8000/api/v1/health

Expected response:

.. code-block:: json

    {"status": "ok", "database": "ok", "version": "1.0.0"}

Submit a Test Story
-------------------

.. code-block:: bash

    curl -X POST http://localhost:8000/api/v1/stories \
        -H "Content-Type: application/json" \
        -H "X-API-Key: my-local-dev-key" \
        -d '{
            "title": "Filter Delivered Orders",
            "description": "Filter the Olist orders dataset to include only delivered orders.",
            "acceptance_criteria": [
                "Output contains only orders where order_status = delivered",
                "Row count is greater than 0"
            ]
        }'

The response includes a ``run_id``. Poll the status:

.. code-block:: bash

    curl http://localhost:8000/api/v1/runs/<run_id> \
        -H "X-API-Key: my-local-dev-key"

Run Tests
---------

.. code-block:: bash

    # Unit tests only (fast, no AWS/DB required)
    uv run pytest tests/unit/ -v -m unit

    # Integration tests (requires LocalStack running)
    uv run pytest tests/integration/ -v -m integration

    # All tests with coverage
    uv run pytest tests/ --cov=src/etl_agent --cov-report=term-missing

Run Linting and Type Checking
------------------------------

.. code-block:: bash

    # Ruff linter
    uv run ruff check src/ tests/

    # Ruff formatter (check only)
    uv run ruff format --check src/ tests/

    # Apply formatting
    uv run ruff format src/ tests/

    # mypy type checker
    uv run mypy src/

Access the UIs
--------------

============================================== ================================
Service                                        URL
============================================== ================================
ETL Agent API (Swagger)                        http://localhost:8000/docs
ETL Agent Web UI                               http://localhost:8000
Airflow Web UI (admin/admin)                   http://localhost:8080
============================================== ================================

Stopping the Local Stack
------------------------

.. code-block:: bash

    docker compose -f infra/docker-compose.yml down

To also remove volumes (destroys all local data):

.. code-block:: bash

    docker compose -f infra/docker-compose.yml down -v
