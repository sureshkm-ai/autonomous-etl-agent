Docker Setup
============

Docker Image
------------

The project ships a single multi-stage ``Dockerfile`` at ``infra/Dockerfile``.
One image serves both the API service (default ``CMD``) and the worker service
(``CMD`` overridden in the ECS task definition).

Multi-Stage Build
~~~~~~~~~~~~~~~~~

**Stage 1 — builder** (``python:3.12-slim``)
    Installs ``uv`` (a fast pip replacement) and uses it to resolve and install all
    production Python dependencies into a virtual environment at ``/app/.venv``.
    Only ``pyproject.toml``, ``uv.lock``, and ``README.md`` are copied in this stage so that
    dependency installation is cached by Docker layer caching — changing application
    source code does not invalidate the dependency layer.

.. code-block:: dockerfile

    FROM python:3.12-slim AS builder
    RUN pip install --no-cache-dir uv==0.4.29
    WORKDIR /app
    COPY pyproject.toml uv.lock* README.md ./
    RUN uv venv .venv && uv sync --frozen --no-dev

**Stage 2 — runtime** (``python:3.12-slim``)
    Installs only the OS packages needed at runtime (``curl`` for the ECS health check,
    ``openjdk-21-jre-headless`` for PySpark, and ``procps`` for debugging via ECS Exec).
    The compiled venv is copied from the builder stage. Application source is copied
    fresh on every build. The container runs as a non-root user (``appuser``, UID 1001).

.. code-block:: dockerfile

    FROM python:3.12-slim AS runtime
    RUN apt-get update && apt-get install -y curl procps openjdk-21-jre-headless
    ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
    RUN useradd --uid 1001 --gid appgroup --no-create-home appuser
    COPY --from=builder /app/.venv /app/.venv
    COPY src/ ./src/
    ENV PATH="/app/.venv/bin:$PATH"
    ENV PYTHONPATH="/app/src"
    USER appuser

Environment Variables Set in Image
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Value / Purpose
   * - JAVA_HOME
     - ``/usr/lib/jvm/java-21-openjdk-amd64``
   * - PATH
     - Prepended with ``$JAVA_HOME/bin`` and ``.venv/bin``
   * - PYTHONPATH
     - ``/app/src``
   * - PYTHONDONTWRITEBYTECODE
     - ``1`` — no ``.pyc`` files written
   * - PYTHONUNBUFFERED
     - ``1`` — stdout/stderr not buffered (important for logs)
   * - PYSPARK_SUBMIT_ARGS
     - ``--master local[*] pyspark-shell``
   * - SPARK_LOCAL_HOSTNAME
     - ``localhost``
   * - GIT_SHA
     - Injected at build time via ``--build-arg GIT_SHA``

Health Check
~~~~~~~~~~~~

The image declares a ``HEALTHCHECK`` that polls ``GET http://localhost:8000/api/v1/health``
every 30 seconds (5 s timeout, 3 retries, 60 s start period). The ECS ALB health check
is configured separately to the same endpoint. Worker containers have no HTTP port;
ECS infers worker health from the process being alive.

Default CMD vs Worker CMD
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: dockerfile

    # Default (API mode):
    CMD ["uvicorn", "etl_agent.api.main:app",
         "--host", "0.0.0.0", "--port", "8000",
         "--workers", "2", "--log-level", "info"]

The worker ECS task definition overrides this with:

.. code-block:: json

    "command": ["python", "-m", "etl_agent.worker"]

Docker Compose (Local Development)
------------------------------------

``infra/docker-compose.yml`` defines a full local development stack with eight services.
Run with:

.. code-block:: bash

    cp .env.example .env   # fill in your values
    docker compose -f infra/docker-compose.yml up -d

Services
~~~~~~~~

**postgres** (``postgres:16-alpine``)
    Primary database. Initialised by ``infra/postgres-init.sql`` which creates the
    ``etl_agent`` and ``airflow`` schemas. Health check: ``pg_isready``.

    ============ ==========
    Setting      Value
    ============ ==========
    User         etl_user
    Password     etl_pass
    Database     etl_agent
    Port         5432
    ============ ==========

**redis** (``redis:7-alpine``)
    Used as the Celery broker for Airflow and as an optional LLM response cache.
    Exposed on port 6379.

**localstack** (``localstack/localstack:3.8``)
    Emulates S3, STS, and IAM locally so the application can run without real AWS
    credentials. Exposed on port 4566. Set ``AWS_ENDPOINT_URL=http://localstack:4566``
    in ``.env`` to redirect boto3 calls here.

**app** (built from ``infra/Dockerfile``)
    The FastAPI application in API mode, running against the local postgres and localstack.
    Exposed on port 8000. Depends on postgres, redis, and localstack being healthy.

**airflow-init**
    One-shot service that runs ``airflow db migrate`` and creates the admin user.
    Runs only once; other Airflow services wait for it to complete successfully.

**airflow-webserver** (``apache/airflow:2.10.0-python3.12``)
    Airflow UI exposed on port 8080. Login: ``admin / admin``.

**airflow-scheduler**
    Airflow scheduler that parses and runs DAGs from ``orchestration/airflow/dags/``.

**airflow-worker**
    Celery worker that executes DAG tasks.

All Airflow services share a common environment block (``x-airflow-common``) that points
them at the local postgres for the backend database and Redis for the Celery broker.
AWS calls from Airflow DAGs are redirected to LocalStack via ``AWS_ENDPOINT_URL``.

Build the Image Manually
------------------------

.. code-block:: bash

    docker build \
        --file infra/Dockerfile \
        --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
        --tag etl-agent-app:local \
        .

Run the API Container Locally (without Compose)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    docker run --rm \
        --env-file .env \
        -p 8000:8000 \
        etl-agent-app:local

Push to ECR (CD pipeline does this automatically)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    aws ecr get-login-password --region us-east-1 | \
        docker login --username AWS \
        --password-stdin 453711491609.dkr.ecr.us-east-1.amazonaws.com

    docker tag etl-agent-app:local \
        453711491609.dkr.ecr.us-east-1.amazonaws.com/etl-agent-app:$(git rev-parse HEAD)

    docker push \
        453711491609.dkr.ecr.us-east-1.amazonaws.com/etl-agent-app:$(git rev-parse HEAD)
