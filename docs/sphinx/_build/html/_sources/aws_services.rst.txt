AWS Services
============

The platform uses the following AWS services, all provisioned by Terraform in
``infra/terraform/``. Every resource is tagged with ``Project=etl-agent`` and
``Environment=production``.

VPC & Networking
----------------

**VPC** (``10.0.0.0/16``)
    A dedicated VPC isolates all project resources. DNS hostnames and DNS support are enabled
    so ECS containers can resolve RDS and endpoint hostnames by DNS name.

**Public Subnets** (×2, one per AZ)
    The Application Load Balancer lives here. Tasks launched in public subnets receive a
    public IP, but ECS Fargate tasks are placed in private subnets instead.

**Private Subnets** (×2, one per AZ)
    ECS Fargate tasks and the RDS instance run here with no direct internet route. Outbound
    traffic exits via NAT Gateway.

**NAT Gateways** (×2, one per AZ)
    Each private subnet routes outbound internet traffic (Anthropic API, GitHub API) through
    a dedicated NAT Gateway + Elastic IP for high availability.

**Internet Gateway**
    Provides inbound/outbound internet access for the public subnets (ALB).

**VPC Endpoints**
    Interface and gateway endpoints route traffic to AWS services without traversing the
    public internet, reducing NAT Gateway data transfer costs:

    ======================= ========= ===========================================
    Service                 Type      Purpose
    ======================= ========= ===========================================
    S3                      Gateway   Read/write raw, processed, artifacts buckets
    SQS                     Interface API service publishes; worker consumes
    ECR API                 Interface Pull task definition metadata
    ECR DKR                 Interface Pull Docker image layers
    CloudWatch Logs         Interface ECS container log delivery
    Secrets Manager         Interface Inject secrets into containers at startup
    Glue                    Interface Data Catalog queries from ECS tasks
    ======================= ========= ===========================================

ECR (Elastic Container Registry)
---------------------------------

A single private ECR repository (``etl-agent-app``) stores all Docker images.
Images are tagged by Git SHA (``<account>.dkr.ecr.<region>.amazonaws.com/etl-agent-app:<sha>``).
Image scanning on push is enabled to detect known CVEs. The CD pipeline also pushes a
``:latest`` tag for use as a Docker build cache on the next run.

ECS Fargate
-----------

**Cluster** (``etl-agent-cluster``)
    Container Insights (CloudWatch) is enabled for task-level CPU, memory, and network metrics.
    Both ``FARGATE`` and ``FARGATE_SPOT`` capacity providers are registered; the default
    strategy uses on-demand Fargate.

**API Service** (``etl-agent-api``)
    Runs the FastAPI application.

    ========================= ================================================
    Setting                   Value
    ========================= ================================================
    CPU                       512 vCPU (0.5 vCPU)
    Memory                    1024 MB
    Desired count             2 (configurable via ``api_desired_count``)
    Min / Max (autoscaling)   1 / 4
    Scaling trigger           CPU ≥ 70 % (scale-out cooldown 60 s)
    Health check              ``GET /api/v1/health`` → HTTP 200
    Load balancer             ALB target group, port 8000
    ========================= ================================================

**Worker Service** (``etl-agent-worker``)
    Runs the SQS consumer loop. One task = one in-flight pipeline run.

    ========================= ================================================
    Setting                   Value
    ========================= ================================================
    CPU                       4096 vCPU (4 vCPU)
    Memory                    8192 MB (8 GB — for PySpark JVM heap)
    Ephemeral storage         30 GiB (PySpark temp files, .whl packaging)
    Desired count             0 at rest (scales from SQS depth)
    Min / Max (autoscaling)   0 / 10
    Scaling trigger           1 worker per visible SQS message
    Scale-in cooldown         120 s; scale-out cooldown 30 s
    ========================= ================================================

Application Load Balancer (ALB)
--------------------------------

An internet-facing ALB sits in the public subnets and forwards HTTP traffic to the
ECS API service. Two listener configurations exist in the Terraform, selected by the
``acm_certificate_arn`` variable:

* **HTTP only** (``acm_certificate_arn = ""``) — port 80 forwards directly to the target
  group. Used in the current production deployment.
* **HTTPS + redirect** (``acm_certificate_arn`` set) — port 443 terminates TLS using the
  provided ACM certificate; port 80 issues a 301 redirect to 443.

The ALB health check polls ``GET /api/v1/health`` every 30 seconds and requires 2
consecutive successes before marking a task healthy (3 failures = unhealthy).

RDS PostgreSQL 16
-----------------

A managed PostgreSQL 16 instance stores all pipeline run state, user stories, and
audit events.

======================= ===================================================
Setting                 Value
======================= ===================================================
Instance class          ``db.t3.small`` (configurable)
Storage                 20 GB gp3, auto-scales to 100 GB
Encryption              At rest (AWS-managed key)
Multi-AZ                Enabled by default (``db_multi_az = true``)
Backup retention        7 days, daily window 03:00–04:00 UTC
Slow query logging      Queries > 1 000 ms logged to CloudWatch
Performance Insights    Enabled, 7-day retention
Deletion protection     Enabled — must be manually disabled to destroy
Final snapshot          Created automatically on ``terraform destroy``
======================= ===================================================

The database is placed in private subnets and is not publicly accessible. Only the
ECS task security group (``ecs-tasks-sg``) is allowed to connect on port 5432.

Migrations are run as an ECS one-off task during the CD pipeline (``alembic upgrade head``)
before the new application image is deployed to the services.

S3 (Simple Storage Service)
----------------------------

Three buckets are created, all with public access blocked:

**etl-agent-raw-production**
    Stores the source data for pipeline runs. The Olist dataset is uploaded here
    under the ``olist/`` prefix, organised into one subfolder per dataset:
    ``olist/orders/``, ``olist/customers/``, etc. (CSV files).

**etl-agent-processed-production**
    Destination for pipeline output data. Generated PySpark jobs write their results
    here. The ``OUTPUT_DATA_BUCKET`` environment variable points containers at this bucket.

**etl-agent-artifacts-production**
    Stores versioned ``.whl`` pipeline packages. Versioning is enabled. Key structure:
    ``artifacts/<pipeline_name>/<pipeline_name>.whl``.

An S3 lifecycle policy on the raw bucket transitions objects to
``STANDARD_IA`` after 30 days and to ``GLACIER`` after 90 days.

SQS (Simple Queue Service)
---------------------------

**etl-agent-pipeline** (main queue)
    Receives pipeline job messages from the API service. Each message contains the
    ``run_id``, ``story_id``, ``dry_run`` flag, and the full serialised ``UserStory``.

    ========================== ==============================================
    Setting                    Value
    ========================== ==============================================
    Visibility timeout         900 seconds (matches worker pipeline budget)
    Message retention          86 400 seconds (1 day)
    Max message size           256 KB
    Long-poll wait time        20 seconds
    Encryption                 SSE-SQS (``alias/aws/sqs``)
    DLQ after                  3 failed receive attempts
    ========================== ==============================================

**etl-agent-pipeline-dlq** (dead-letter queue)
    Receives messages that failed processing 3 times. Retention: 14 days.
    A CloudWatch alarm fires if any message lands here.

The worker implements a heartbeat loop that calls ``ChangeMessageVisibility`` every
4 minutes to extend the timeout while a long pipeline run is in progress, preventing
premature re-queuing.

AWS Glue Data Catalog
---------------------

The Glue catalog is the project's data model layer. It stores schema metadata for all
available source datasets so that agents can discover what data exists without hardcoding
paths or column names.

**Database**: ``etl_agent_catalog``

**Crawler**: ``etl-agent-olist-crawler``
    Crawls 9 separate S3 target prefixes (one per Olist dataset) to create 9 independent
    tables. The crawler uses the ``AWSGlueServiceRole`` managed policy which grants all
    required Glue + CloudWatch Logs permissions, plus a custom inline S3 policy scoped
    to ``olist/*``.

    .. list-table::
       :header-rows: 1
       :widths: 35 65

       * - Table
         - S3 Path
       * - orders
         - ``s3://etl-agent-raw-prod/olist/orders/``
       * - order_items
         - ``s3://etl-agent-raw-prod/olist/order_items/``
       * - order_payments
         - ``s3://etl-agent-raw-prod/olist/order_payments/``
       * - order_reviews
         - ``s3://etl-agent-raw-prod/olist/order_reviews/``
       * - customers
         - ``s3://etl-agent-raw-prod/olist/customers/``
       * - sellers
         - ``s3://etl-agent-raw-prod/olist/sellers/``
       * - products
         - ``s3://etl-agent-raw-prod/olist/products/``
       * - geolocation
         - ``s3://etl-agent-raw-prod/olist/geolocation/``
       * - product_category_translation
         - ``s3://etl-agent-raw-prod/olist/product_category_translation/``

After the crawler runs, each table is available via ``boto3.client("glue").get_tables()``
and contains the column names and data types inferred from the CSV headers.

AWS Secrets Manager
-------------------

All secrets are stored as a single JSON object in one secret: ``etl-agent/app``.
ECS tasks pull individual keys at startup via the ``secrets`` block in the task definition
(no secrets in environment variables or image layers).

Required keys:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Description
   * - ANTHROPIC_API_KEY
     - Anthropic API key for Claude calls
   * - API_KEY
     - Bearer token for the REST API
   * - GITHUB_TOKEN
     - GitHub Personal Access Token (repo + workflow + issues)
   * - GITHUB_OWNER
     - GitHub username / org that owns the target repo
   * - GITHUB_REPO
     - Target repository name where PRs are created
   * - AWS_S3_ARTIFACTS_BUCKET
     - Name of the artifacts S3 bucket
   * - DATABASE_URL
     - Full asyncpg connection string for RDS
   * - DB_PASSWORD
     - RDS master password (used by Terraform-registered task defs)
   * - SQS_QUEUE_URL
     - Full SQS queue URL for the pipeline queue

IAM
---

**Execution Role** (``etl-agent-ecs-execution``)
    Used by the ECS agent to pull images from ECR and inject secrets from Secrets Manager.
    Attached policies: ``AmazonECSTaskExecutionRolePolicy`` + custom Secrets Manager read policy.

**Task Role** (``etl-agent-ecs-task``)
    Used by running containers to call AWS services at runtime.
    Permissions: S3 read/write (all three buckets), SQS send/receive/delete,
    Glue read (``GetDatabase``, ``GetTables``, ``GetTable``), CloudWatch Logs write,
    Secrets Manager read.

**Glue Crawler Role** (``etl-agent-glue-crawler``)
    Assumed by the Glue service. Attached: ``AWSGlueServiceRole`` managed policy
    (covers all Glue + CloudWatch Logs operations) + inline S3 read policy scoped
    to ``olist/*``.

**RDS Monitoring Role** (``etl-agent-rds-monitoring``)
    Assumed by ``monitoring.rds.amazonaws.com`` for Enhanced Monitoring.
    Attached: ``AmazonRDSEnhancedMonitoringRole``.

CloudWatch
----------

Log groups are created for both ECS services with 30-day retention:

* ``/ecs/etl-agent/api`` — FastAPI access logs + structured JSON application logs
* ``/ecs/etl-agent/worker`` — Worker lifecycle events, pipeline node completions,
  LLM call traces

CloudWatch alarms:

* **RDS high connections** — fires when average DB connection count exceeds 80.
* **SQS DLQ not empty** — fires immediately when any pipeline message lands in the DLQ,
  indicating a failed run that exhausted retries.

Both alarms can be routed to an SNS topic by setting ``alarm_sns_topic_arn`` in
``terraform.tfvars``.
