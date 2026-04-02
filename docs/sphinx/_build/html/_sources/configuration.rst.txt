Configuration Reference
=======================

All configuration is managed through ``pydantic-settings`` (``src/etl_agent/core/config.py``).
Values are read from environment variables or from a ``.env`` file in the project root.
In production, secrets are injected by ECS from AWS Secrets Manager.

.. code-block:: python

    from etl_agent.core.config import get_settings
    settings = get_settings()    # returns a cached Settings instance

LLM
---

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
ANTHROPIC_API_KEY         *(required)*        Anthropic API key for all Claude calls
LLM_MODEL                 claude-sonnet-4-6   Claude model to use
LLM_MAX_TOKENS            8096                Max tokens per LLM response
LLM_TEMPERATURE           0.2                 Sampling temperature (0 = deterministic)
========================= =================== =============================================

API
---

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
API_KEY                   changeme            Bearer token for REST API authentication
API_HOST                  0.0.0.0             Bind address for uvicorn
API_PORT                  8000                Listen port
CORS_ORIGINS              \*                  Comma-separated allowed origins
MAX_REQUEST_BODY_BYTES    32768               Maximum request body size
========================= =================== =============================================

GitHub
------

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
GITHUB_TOKEN              *(required)*        GitHub PAT (repo + workflow + issues scopes)
GITHUB_OWNER              *(required)*        GitHub username or organisation
GITHUB_REPO               *(required)*        Target repository for generated PRs
========================= =================== =============================================

The ``github_target_repo`` derived property concatenates these as ``OWNER/REPO``.

AWS
---

============================= =================== =============================================
Variable                      Default             Description
============================= =================== =============================================
AWS_REGION                    us-east-1           AWS region for all boto3 clients
AWS_ACCESS_KEY_ID             *(optional)*        Explicit credentials (ECS uses task role)
AWS_SECRET_ACCESS_KEY         *(optional)*        Explicit credentials (ECS uses task role)
AWS_ENDPOINT_URL              *(empty)*           Custom endpoint; set to LocalStack in dev
AWS_S3_ARTIFACTS_BUCKET       *(empty)*           S3 bucket name for .whl artifacts
S3_BUCKET                     *(empty)*           Raw data S3 bucket
============================= =================== =============================================

Database
--------

============================= ====================================== ========================
Variable                      Default                                Description
============================= ====================================== ========================
DATABASE_URL                  sqlite+aiosqlite:///./etl_agent.db     SQLAlchemy async URL.
                                                                     Use ``postgresql+asyncpg``
                                                                     in production.
============================= ====================================== ========================

SQS
---

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
SQS_QUEUE_URL             *(empty)*           Full SQS URL. When set, enables ECS Fargate
                                              mode (messages are enqueued vs inline).
SQS_DLQ_URL               *(empty)*           Dead-letter queue URL (informational)
SQS_VISIBILITY_TIMEOUT    900                 Seconds a message is invisible while processing
========================= =================== =============================================

The ``use_sqs`` derived property returns ``True`` when ``SQS_QUEUE_URL`` is non-empty.

Glue Data Catalog
-----------------

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
GLUE_CATALOG_DATABASE     etl_agent_catalog   Glue database name
OUTPUT_DATA_BUCKET        *(empty)*           S3 URI prefix for pipeline output
                                              (e.g. ``s3://etl-agent-processed-production/``)
========================= =================== =============================================

LLM Governance
--------------

================================ =================== =============================================
Variable                         Default             Description
================================ =================== =============================================
MAX_TOKENS_PER_RUN               500000              Per-run token budget cap (all agents combined)
BUDGET_APPROVAL_THRESHOLD_PCT    75.0                % of budget consumed that triggers approval
APPROVED_MODELS                  (see below)         Comma-separated list of approved model names
FALLBACK_MODEL                   claude-sonnet-4-6   Model to use if primary is unavailable
================================ =================== =============================================

Default approved models: ``claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5-20251001``

Pipeline Behaviour
------------------

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
MAX_RETRIES               2                   Max code generation retry cycles if tests fail
REQUIRE_HUMAN_APPROVAL    false               Force approval gate for all runs
AIRFLOW_ENABLED           false               Enable Airflow DAG trigger after deploy
AIRFLOW_API_URL           *(empty)*           Airflow REST API base URL
AIRFLOW_DAG_ID            etl_pipeline        DAG ID to trigger
AIRFLOW_USERNAME          airflow             Airflow basic auth username
AIRFLOW_PASSWORD          airflow             Airflow basic auth password
========================= =================== =============================================

Miscellaneous
-------------

========================= =================== =============================================
Variable                  Default             Description
========================= =================== =============================================
DEBUG                     false               Enable debug logging and hot-reload
REDIS_URL                 *(None)*            Redis URL for optional LLM response cache
ENVIRONMENT               production          Environment label (production / staging)
========================= =================== =============================================

Terraform Variables
-------------------

Infrastructure-level configuration lives in ``infra/terraform/terraform.tfvars``.
Key variables (all defined in ``ecs_variables.tf``):

============================= =================== =============================================
Variable                      Default             Description
============================= =================== =============================================
aws_region                    us-east-1           AWS region for all resources
project_name                  etl-agent           Prefix for all resource names
environment                   production          Used in resource names and tags
s3_bucket                     *(required)*        Raw data S3 bucket name
db_password                   *(required)*        RDS PostgreSQL master password
acm_certificate_arn           *(empty)*           ACM cert for HTTPS; empty = HTTP only
api_desired_count             2                   Initial API task count
api_min_count                 1                   Autoscaling floor
api_max_count                 4                   Autoscaling ceiling
worker_max_count              10                  Max concurrent worker tasks
db_instance_class             db.t3.small         RDS instance type
db_multi_az                   true                Enable Multi-AZ for RDS HA
max_tokens_per_run            500000              Token budget injected as env var
budget_approval_threshold_pct 75                  Approval threshold injected as env var
glue_catalog_database         etl_agent_catalog   Glue database name
alarm_sns_topic_arn           *(empty)*           SNS topic for CloudWatch alarm emails
============================= =================== =============================================
