Deployment (AWS ECS Fargate)
============================

This section covers everything needed to deploy the project to a fresh AWS account.

Prerequisites
-------------

* AWS CLI v2 configured with credentials for the target account
* Terraform >= 1.9.0 (``brew install terraform``)
* Docker Desktop (for local image builds if needed)
* GitHub account + Personal Access Token (``repo``, ``workflow``, ``issues`` scopes)
* Anthropic API key

Step 1 — Bootstrap Secrets Manager
------------------------------------

The Terraform plan reads the Secrets Manager secret at plan time. Create it with
placeholder values first, then update with real values after infrastructure is up.

.. code-block:: bash

    aws secretsmanager create-secret \
        --name etl-agent/app \
        --secret-string '{
            "DATABASE_URL": "placeholder",
            "SQS_QUEUE_URL": "placeholder",
            "ANTHROPIC_API_KEY": "YOUR_ANTHROPIC_KEY",
            "API_KEY": "choose-any-random-string",
            "GITHUB_TOKEN": "YOUR_GITHUB_PAT",
            "GITHUB_OWNER": "YOUR_GITHUB_USERNAME",
            "GITHUB_REPO": "YOUR_TARGET_REPO_NAME",
            "AWS_S3_ARTIFACTS_BUCKET": "etl-agent-artifacts-production",
            "DB_PASSWORD": "YOUR_RDS_PASSWORD"
        }'

Step 2 — Configure Terraform Variables
-----------------------------------------

.. code-block:: bash

    cd infra/terraform

Edit ``terraform.tfvars``:

.. code-block:: hcl

    s3_bucket           = "etl-agent-raw-prod"          # must be globally unique
    db_password         = "YourSecurePassword123!"
    acm_certificate_arn = ""                             # leave empty for HTTP-only

.. warning::

    Never commit ``terraform.tfvars`` or ``terraform.tfstate`` to version control.
    Both may contain secrets.

Step 3 — Apply Infrastructure
-------------------------------

.. code-block:: bash

    cd infra/terraform
    terraform init
    terraform plan
    terraform apply

Terraform creates the following resources (in dependency order):

1. VPC, subnets, IGW, NAT Gateways, route tables, VPC endpoints
2. S3 buckets (raw, processed, artifacts)
3. ECR repository
4. RDS PostgreSQL instance (takes 10–15 minutes)
5. SQS queues (pipeline + DLQ)
6. Glue catalog database, IAM role, crawler
7. ECS cluster, task definitions, services
8. ALB, target group, listeners
9. CloudWatch log groups, alarms
10. IAM roles for ECS execution, task, RDS monitoring

The full ``terraform apply`` takes approximately 20–25 minutes, dominated by RDS creation.

Step 4 — Upload Olist Data & Run Glue Crawler
----------------------------------------------

.. code-block:: bash

    # Upload the 9 CSV files (see olist_data section for download instructions)
    BUCKET=etl-agent-raw-prod
    aws s3 cp olist/olist_orders_dataset.csv              s3://$BUCKET/olist/orders/
    aws s3 cp olist/olist_order_items_dataset.csv         s3://$BUCKET/olist/order_items/
    aws s3 cp olist/olist_order_payments_dataset.csv      s3://$BUCKET/olist/order_payments/
    aws s3 cp olist/olist_order_reviews_dataset.csv       s3://$BUCKET/olist/order_reviews/
    aws s3 cp olist/olist_customers_dataset.csv           s3://$BUCKET/olist/customers/
    aws s3 cp olist/olist_sellers_dataset.csv             s3://$BUCKET/olist/sellers/
    aws s3 cp olist/olist_products_dataset.csv            s3://$BUCKET/olist/products/
    aws s3 cp olist/olist_geolocation_dataset.csv         s3://$BUCKET/olist/geolocation/
    aws s3 cp olist/product_category_name_translation.csv s3://$BUCKET/olist/product_category_translation/

    # Run the Glue crawler
    aws glue start-crawler --name etl-agent-olist-crawler

    # Wait until state = READY (1–3 minutes)
    aws glue get-crawler --name etl-agent-olist-crawler \
        --query 'Crawler.State' --output text

Step 5 — Configure GitHub Actions Secrets
------------------------------------------

In your GitHub repository, add the following secrets under
**Settings → Secrets and variables → Actions**:

============================== =================================================
Secret                         Value
============================== =================================================
AWS_ACCESS_KEY_ID              IAM user or role access key with ECR/ECS permissions
AWS_SECRET_ACCESS_KEY          Corresponding secret key
AWS_REGION                     ``us-east-1``
ECR_REPOSITORY                 Full ECR URI (e.g. ``453711491609.dkr.ecr.us-east-1.amazonaws.com/etl-agent-app``)
ECS_CLUSTER                    ``etl-agent-cluster``
ECS_API_SERVICE                ``etl-agent-api``
ECS_WORKER_SERVICE             ``etl-agent-worker``
PRIVATE_SUBNET_IDS             Comma-separated private subnet IDs (from Terraform output)
ECS_SECURITY_GROUP_ID          ECS task security group ID (from Terraform output)
============================== =================================================

Get the Terraform outputs:

.. code-block:: bash

    cd infra/terraform
    terraform output

Step 6 — Trigger the CD Pipeline
----------------------------------

Push to the ``main`` branch to trigger the CD pipeline:

.. code-block:: bash

    git commit --allow-empty -m "ci: trigger initial deployment"
    git push origin main

The CD pipeline runs four jobs:

1. **Build & Push** — builds the Docker image and pushes to ECR with the Git SHA tag.
2. **Run DB Migrations** — runs ``alembic upgrade head`` as an ECS one-off task.
3. **Deploy to ECS** — registers new task definitions and updates both ECS services.
   Waits for service stability (up to 30 minutes). This step takes 15–25 minutes.
4. **Smoke Test** — calls ``GET /api/v1/health`` via the ALB DNS name.

Step 7 — Update Secrets with Real Values
-----------------------------------------

After Terraform completes, get the real RDS endpoint and SQS URL:

.. code-block:: bash

    # RDS endpoint
    aws rds describe-db-instances \
        --query 'DBInstances[0].Endpoint.Address' --output text

    # SQS queue URL
    aws sqs get-queue-url \
        --queue-name etl-agent-pipeline \
        --query 'QueueUrl' --output text

Update the secret:

.. code-block:: bash

    aws secretsmanager put-secret-value \
        --secret-id etl-agent/app \
        --secret-string '{
            "DATABASE_URL": "postgresql+asyncpg://etlagent:YOUR_PASSWORD@RDS_ENDPOINT:5432/etl_agent",
            "SQS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/etl-agent-pipeline",
            "ANTHROPIC_API_KEY": "YOUR_ANTHROPIC_KEY",
            "API_KEY": "YOUR_API_KEY",
            "GITHUB_TOKEN": "YOUR_GITHUB_PAT",
            "GITHUB_OWNER": "YOUR_GITHUB_USERNAME",
            "GITHUB_REPO": "YOUR_TARGET_REPO",
            "AWS_S3_ARTIFACTS_BUCKET": "etl-agent-artifacts-production",
            "DB_PASSWORD": "YOUR_RDS_PASSWORD"
        }'

Force a new deployment so ECS picks up the updated secret:

.. code-block:: bash

    aws ecs update-service \
        --cluster etl-agent-cluster \
        --service etl-agent-worker \
        --force-new-deployment

    aws ecs update-service \
        --cluster etl-agent-cluster \
        --service etl-agent-api \
        --force-new-deployment

Step 8 — Verify Deployment
---------------------------

.. code-block:: bash

    # Get the ALB DNS name
    ALB=$(aws elbv2 describe-load-balancers \
        --names etl-agent-alb \
        --query 'LoadBalancers[0].DNSName' --output text)

    echo "Application URL: http://${ALB}"

    # Health check
    curl -s "http://${ALB}/api/v1/health" | python3 -m json.tool

    # Submit a test story
    curl -X POST "http://${ALB}/api/v1/stories" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: YOUR_API_KEY" \
        -d '{
            "title": "Filter Delivered Orders",
            "description": "Filter Olist orders to include only delivered orders.",
            "acceptance_criteria": ["Only delivered status rows", "Row count > 0"]
        }'

Worker Scaling
--------------

The worker service starts at ``desired_count=0``. It scales up automatically when
messages are visible in the SQS queue (SQS-depth autoscaling policy: 1 worker per
message, max 10 workers).

To manually scale the worker to 1 (useful for testing or when autoscaling lags):

.. code-block:: bash

    aws ecs update-service \
        --cluster etl-agent-cluster \
        --service etl-agent-worker \
        --desired-count 1

Tearing Down
------------

To destroy all AWS resources:

.. code-block:: bash

    cd infra/terraform

    # Deletion protection must be disabled on RDS before destroy
    aws rds modify-db-instance \
        --db-instance-identifier etl-agent-postgres \
        --no-deletion-protection \
        --apply-immediately

    terraform destroy

.. warning::

    ``terraform destroy`` creates a final RDS snapshot before deletion. The snapshot
    is not managed by Terraform and must be deleted manually if not needed.
    NAT Gateways incur hourly charges — destroy promptly when not in use.

HTTPS Configuration
--------------------

To enable HTTPS:

1. Request an ACM certificate for your domain in the AWS Console
   (Certificate Manager → Request a public certificate).
2. Add the DNS validation CNAME record to your DNS provider.
3. Wait for the certificate status to become ``ISSUED``.
4. Update ``terraform.tfvars``:

   .. code-block:: hcl

       acm_certificate_arn = "arn:aws:acm:us-east-1:ACCOUNT:certificate/UUID"

5. Run ``terraform apply`` — this creates the HTTPS listener and HTTP→HTTPS redirect.
6. Point a DNS record (CNAME or ALIAS) at the ALB DNS name.

.. note::

    ACM certificates may fail with a CAA error if the domain's DNS has CAA records that
    exclude Amazon. Check your DNS provider's CAA settings and add a record allowing
    ``amazon.com`` if needed.
