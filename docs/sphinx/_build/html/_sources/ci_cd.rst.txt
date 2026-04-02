CI/CD Pipeline
==============

The project uses two GitHub Actions workflows defined in ``.github/workflows/``:

* ``ci.yml`` — runs on every push to every branch and on pull requests to ``main``
* ``cd.yml`` — runs only on pushes to ``main``

CI Workflow (ci.yml)
---------------------

Runs four parallel jobs. All jobs use ``uv sync`` to install dependencies and
``astral-sh/setup-uv@v4`` to install the ``uv`` tool.

**Lint & Format** (job: ``lint``)
    Runs two checks against ``src/`` and ``tests/``:

    1. ``uv run ruff check src/ tests/`` — enforces PEP 8, import order, unused
       variables, exception chaining, and ~40 other rules.
    2. ``uv run ruff format --check src/ tests/`` — verifies Black-compatible
       formatting (88-char line limit).

    Fails immediately if any violation is found. Fix locally with:

    .. code-block:: bash

        uv run ruff check --fix src/ tests/
        uv run ruff format src/ tests/

**Type Check** (job: ``typecheck``)
    Runs ``uv run mypy src/`` with strict type checking enabled for all
    ``src/etl_agent/`` modules except those explicitly relaxed in ``pyproject.toml``
    (e.g., modules that use untyped third-party libraries).

**Unit Tests** (job: ``test-unit``)
    Runs ``uv run pytest tests/unit/ -v -m unit --cov=src/etl_agent --cov-report=xml``

    Required environment variables are injected as ``env:`` blocks with test values:

    * ``ANTHROPIC_API_KEY=test-key``
    * ``GITHUB_TOKEN=test-token``
    * ``GITHUB_TARGET_REPO=test/repo``
    * ``AWS_ACCESS_KEY_ID=test``, ``AWS_SECRET_ACCESS_KEY=test``
    * ``AWS_S3_RAW_BUCKET``, ``AWS_S3_PROCESSED_BUCKET``, ``AWS_S3_ARTIFACTS_BUCKET``
    * ``AWS_ENDPOINT_URL=http://localhost:4566``
    * ``API_KEY=test-api-key``

    Coverage results are uploaded to Codecov.

**Integration Tests** (job: ``test-integration``)
    Runs ``uv run pytest tests/integration/ -v -m integration``.
    Same environment variables as unit tests.

CD Workflow (cd.yml)
---------------------

Triggers on push to ``main`` only. Runs four sequential jobs.

**Job 1 — Build & Push Image**
    1. Checks out the code.
    2. Configures AWS credentials using ``aws-actions/configure-aws-credentials@v4``.
    3. Logs in to ECR using ``aws-actions/amazon-ecr-login@v2``.
    4. Runs ``docker build`` with:

       * ``--file infra/Dockerfile``
       * ``--build-arg GIT_SHA=$GITHUB_SHA``
       * ``--tag <ECR_REPO>:<GITHUB_SHA>``
       * ``--cache-from <ECR_REPO>:latest`` (speeds up repeated builds)

    5. Pushes the SHA-tagged image and updates the ``:latest`` tag.

**Job 2 — Run DB Migrations** (depends on Job 1)
    1. Uses ``aws-actions/amazon-ecs-render-task-definition@v1`` to render the API
       task definition with the newly-built image SHA.
    2. Registers the rendered task definition with ECS.
    3. Runs ``aws ecs run-task`` with a command override:
       ``alembic -c src/etl_agent/database/migrations/alembic.ini upgrade head``
    4. Waits up to 5 minutes for the migration task to complete.
    5. Retrieves the exit code and CloudWatch logs. Fails the job if exit code ≠ 0.

    This ensures the database schema is updated *before* the new code is deployed
    to the services, preventing schema-mismatch errors during the rolling update.

**Job 3 — Deploy to ECS** (depends on Job 2)
    Deploys both services sequentially:

    **API service**:

    1. Renders ``infra/ecs-task-def-api.json`` with the new image.
    2. Uses ``aws-actions/amazon-ecs-deploy-task-definition@v1`` with
       ``wait-for-service-stability: true``.
    3. ECS performs a rolling update — starts new tasks, waits for ALB health checks
       to pass, drains old tasks. Takes 5–15 minutes.

    **Worker service**:

    1. Checks if the worker's ``desiredCount`` is 0. If so, scales it to 1 before
       deploying (ensures the new task definition is tested on a running task).
    2. Renders ``infra/ecs-task-def-worker.json`` with the new image.
    3. Deploys with ``wait-for-service-stability: true``.

    The deployment step fails with ``Resource is not in the state servicesStable``
    if a service does not stabilise within 30 minutes (ECS default timeout).
    The most common causes are: secrets missing from Secrets Manager, insufficient
    IAM permissions, or a container crash on startup (check CloudWatch Logs).

**Job 4 — Smoke Test** (depends on Job 3)
    1. Discovers the ALB DNS name via ``aws elbv2 describe-load-balancers``.
    2. Waits 15 seconds for the new tasks to be fully serving.
    3. Calls ``curl --fail http://<ALB_DNS>/api/v1/health`` and prints the JSON response.
    4. Fails the pipeline if the health check returns a non-2xx status.

Required GitHub Secrets
-----------------------

All secrets are read from the repository's Actions secrets:

======================== =======================================================
Secret                   Description
======================== =======================================================
AWS_ACCESS_KEY_ID        AWS IAM credentials with ECR push and ECS deploy rights
AWS_SECRET_ACCESS_KEY    Corresponding secret key
AWS_REGION               AWS region (e.g. ``us-east-1``)
ECR_REPOSITORY           Full ECR repository URI
ECS_CLUSTER              ECS cluster name (``etl-agent-cluster``)
ECS_API_SERVICE          API ECS service name (``etl-agent-api``)
ECS_WORKER_SERVICE       Worker ECS service name (``etl-agent-worker``)
PRIVATE_SUBNET_IDS       Comma-separated private subnet IDs (for migration task)
ECS_SECURITY_GROUP_ID    ECS task security group ID (for migration task)
======================== =======================================================

Common CI Failures and Fixes
------------------------------

**Lint & Format fails**

    Run locally to see and fix all violations:

    .. code-block:: bash

        uv run ruff check --fix src/ tests/
        uv run ruff format src/ tests/

**Unit tests fail with exit code 5 (no tests collected)**

    This means pytest found no tests matching the ``-m unit`` marker. Check that
    every test function in ``tests/unit/`` has ``@pytest.mark.unit``.

**Deploy to ECS fails — "Resource is not in the state servicesStable"**

    Check CloudWatch Logs for the failing service:

    .. code-block:: bash

        aws logs tail /ecs/etl-agent/worker --since 30m
        aws logs tail /ecs/etl-agent/api --since 30m

    Check the stopped task for the failure reason:

    .. code-block:: bash

        aws ecs describe-tasks \
            --cluster etl-agent-cluster \
            --tasks $(aws ecs list-tasks \
                --cluster etl-agent-cluster \
                --service-name etl-agent-worker \
                --desired-status STOPPED \
                --query 'taskArns[0]' --output text) \
            --query 'tasks[0].{stopCode:stopCode,stopReason:stoppedReason}' \
            --output table

    Common root causes:

    * ``TaskFailedToStart`` with ``did not contain json key <KEY>`` → add the missing
      key to the ``etl-agent/app`` Secrets Manager secret.
    * Container exits with non-zero code → application error; check CloudWatch Logs.
    * ``CannotPullContainerError`` → ECR permissions issue or image tag does not exist.

**CD pipeline: worker service stays at desired=0**

    The Terraform worker service is created with ``desired_count=0``. The CD pipeline
    has a step to bump it to 1 before deployment. If the pipeline failed before that
    step, manually scale it:

    .. code-block:: bash

        aws ecs update-service \
            --cluster etl-agent-cluster \
            --service etl-agent-worker \
            --desired-count 1
