# ECS Migration — Steps 2, 3 & 4 Reference

> **Account:** `453711491609`  **Region:** `us-east-1`  **Project:** `etl-agent`

---

## Step 2 — Create the Secrets Manager secret

Run **once** to create the secret. Substitute each `<…>` with your real value.

```bash
aws secretsmanager create-secret \
  --name "etl-agent/app" \
  --description "ETL Agent application secrets" \
  --region us-east-1 \
  --secret-string '{
    "ANTHROPIC_API_KEY":  "<your-anthropic-api-key>",
    "API_KEY":            "<your-etl-agent-api-key>",
    "GITHUB_TOKEN":       "<your-github-pat>",
    "DATABASE_URL":       "postgresql+asyncpg://etlagent:<db-password>@<rds-endpoint>:5432/etlagent",
    "SQS_QUEUE_URL":      "https://sqs.us-east-1.amazonaws.com/453711491609/etl-agent-pipeline"
  }'
```

> **Note:** After `terraform apply` the RDS endpoint will appear in `terraform output rds_endpoint`
> and the SQS URL in `terraform output sqs_pipeline_url`. You can then **update** the secret:
>
> ```bash
> aws secretsmanager put-secret-value \
>   --secret-id "etl-agent/app" \
>   --region us-east-1 \
>   --secret-string '{
>     "ANTHROPIC_API_KEY":  "<same-as-before>",
>     "API_KEY":            "<same-as-before>",
>     "GITHUB_TOKEN":       "<same-as-before>",
>     "DATABASE_URL":       "postgresql+asyncpg://etlagent:<db-password>@<real-rds-endpoint>:5432/etlagent",
>     "SQS_QUEUE_URL":      "<real-sqs-url-from-terraform-output>"
>   }'
> ```

---

## Step 3 — Complete `terraform.tfvars`

`infra/terraform/terraform.tfvars` has been updated and is already git-ignored.

Two values still need to be filled in before `terraform apply`:

### 3a — Database password (never hardcode; use environment variable)
```bash
export TF_VAR_db_password="<choose-a-strong-password>"
```
Use the same password in the `DATABASE_URL` secret above.

### 3b — ACM Certificate ARN
You need an SSL certificate in **us-east-1** for the ALB HTTPS listener.

```bash
# List existing certificates
aws acm list-certificates --region us-east-1

# Or request a new one (DNS validation recommended)
aws acm request-certificate \
  --domain-name "api.yourdomain.com" \
  --validation-method DNS \
  --region us-east-1
```

Once you have the ARN, uncomment and set this line in `terraform.tfvars`:
```hcl
acm_certificate_arn = "arn:aws:acm:us-east-1:453711491609:certificate/<uuid>"
```

### 3c — Run Terraform
```bash
cd infra/terraform

# Init (first time, or after adding new providers)
terraform init

# Preview changes
terraform plan

# Apply — EC2 resources in ec2_bkp.tf are inactive; only ECS/RDS/SQS will be created
terraform apply
```

After apply, capture the outputs you'll need for the GitHub secrets in Step 4:
```bash
terraform output -json > /tmp/tf_outputs.json
cat /tmp/tf_outputs.json
```

---

## Step 4 — Set GitHub Actions secrets

Go to **GitHub → your repo → Settings → Secrets and variables → Actions → New repository secret**
and add each of the following. Values marked `(from terraform output)` come from Step 3c.

| Secret name | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | Your CI/CD IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | Your CI/CD IAM user secret key |
| `AWS_REGION` | `us-east-1` |
| `ECR_REPOSITORY` | `453711491609.dkr.ecr.us-east-1.amazonaws.com/etl-agent-app` |
| `ECS_CLUSTER` | `etl-agent-cluster` *(from terraform output `ecs_cluster_name`)* |
| `ECS_API_SERVICE` | `etl-agent-api` *(from terraform output `api_service_name`)* |
| `ECS_WORKER_SERVICE` | `etl-agent-worker` *(from terraform output `worker_service_name`)* |
| `PRIVATE_SUBNET_IDS` | Comma-separated subnet IDs *(from terraform output `private_subnet_ids`)* |
| `ECS_SECURITY_GROUP_ID` | Security group ID *(from terraform output `ecs_tasks_security_group_id`)* |

### Set them via GitHub CLI (faster)

```bash
# Authenticate first if needed: gh auth login

REPO="your-org/your-repo"   # <-- change this

gh secret set AWS_ACCESS_KEY_ID        --repo $REPO --body "<access-key-id>"
gh secret set AWS_SECRET_ACCESS_KEY    --repo $REPO --body "<secret-access-key>"
gh secret set AWS_REGION               --repo $REPO --body "us-east-1"
gh secret set ECR_REPOSITORY           --repo $REPO --body "453711491609.dkr.ecr.us-east-1.amazonaws.com/etl-agent-app"
gh secret set ECS_CLUSTER              --repo $REPO --body "etl-agent-cluster"
gh secret set ECS_API_SERVICE          --repo $REPO --body "etl-agent-api"
gh secret set ECS_WORKER_SERVICE       --repo $REPO --body "etl-agent-worker"

# After terraform apply — grab subnet IDs and security group ID:
PRIVATE_SUBNETS=$(terraform -chdir=infra/terraform output -raw private_subnet_ids 2>/dev/null || echo "subnet-XXXX,subnet-YYYY")
ECS_SG=$(terraform -chdir=infra/terraform output -raw ecs_tasks_security_group_id 2>/dev/null || echo "sg-XXXXXXXXXXXXXXXXX")

gh secret set PRIVATE_SUBNET_IDS       --repo $REPO --body "$PRIVATE_SUBNETS"
gh secret set ECS_SECURITY_GROUP_ID    --repo $REPO --body "$ECS_SG"
```

---

## Recommended order of operations

```
1. export TF_VAR_db_password="..."       # Step 3a
2. Get ACM cert ARN, update tfvars       # Step 3b
3. terraform init && terraform apply     # Step 3c
4. Create Secrets Manager secret         # Step 2
5. Set GitHub Actions secrets            # Step 4
6. git push → CD pipeline fires         # Triggers build → migrate → deploy → smoke-test
```

---

## Verification checklist

- [ ] `terraform apply` completes with no errors
- [ ] `aws ecs describe-services --cluster etl-agent-cluster --services etl-agent-api` shows `ACTIVE`
- [ ] `curl https://<alb-dns>/api/v1/health` returns `{"status":"ok"}`
- [ ] `aws sqs get-queue-attributes --queue-url <sqs-url>` shows queue exists
- [ ] GitHub Actions CD run succeeds end-to-end on next push to `main`
