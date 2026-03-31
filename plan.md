# Implementation Plan: Simplified Story Submission + AWS Glue Data Catalog

**Status:** Awaiting approval — all 21 files read; no remaining hidden issues
**Last reviewed:** 2026-03-31 — Final file-by-file review pass complete. All 7 rounds of review resolved: IAM scoping, VPC endpoint, hardcoded values, dead code, None guards, missing imports, Terraform variable duplication, var.s3_bucket/Crawler alignment. Plan is stable.
**Author:** Claude (Cowork)

---

## 1. Problem Statement

### What is wrong today

Users must manually supply technical infrastructure details when submitting a story:

- `source.path` — exact S3 URI
- `source.format` — parquet / csv / delta
- `target.path` — exact S3 URI
- `target.format`
- `transformations` — a structured list of operations

This defeats the purpose of an autonomous agent. Users should not need to know where data lives.

Additionally, the agent previously had no understanding of the data model. It generated PySpark code using invented or assumed column names. There was no actual source data in S3 (`etl-agent-raw-prod` is empty), so schema inference from files was impossible.

### What we want instead

A user submits only:

- **Title** — "Monthly Revenue by Product Category"
- **Description** — plain English description of what the pipeline should do
- **Acceptance Criteria** — bullet list of testable outcomes

The agent resolves everything else: which datasets are involved, their S3 paths, their schemas, the transformations needed, and where to write the output.

---

## 2. Solution Architecture

### Two pillars

**Pillar 1 — AWS Glue Data Catalog as the Data Model**

The Glue Data Catalog is AWS's purpose-built, fully managed metadata registry. It stores the schema (column names and types), S3 location, and format for every registered dataset. It is viewable in the AWS Console, queryable via boto3, and populated automatically by a Glue Crawler.

**Pillar 2 — Glue Crawler for Auto Schema Discovery**

A Glue Crawler points at `s3://etl-agent-raw-prod/olist/`, scans all 9 Olist CSV files, and populates the Glue catalog with their schemas automatically. No pyarrow. No manual schema entry. No custom inference code.

### Source Dataset: Olist Brazilian E-Commerce

The Olist dataset (100k orders, 2016–2018) is downloaded from Kaggle and uploaded to S3 as CSV files. It provides 9 related tables covering orders, customers, products, payments, reviews, sellers, and geolocation — enabling rich ETL scenarios including joins, aggregations, enrichments, and time-series analysis.

---

## 3. When Does the Agent Check the Data Catalog?

The catalog is consulted **twice** during a single pipeline run, at two different nodes for two different purposes.

```
User submits {title, description, acceptance_criteria}
        │
        ▼
[API] Creates internal UserStory → publishes to SQS
        │
        ▼
[Worker] Picks up SQS message → calls stream_pipeline()
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  Node 1: parse_story                                │
│  StoryParserAgent calls DataCatalogClient           │
│  .list_entities() → fetches ALL 9 Glue tables      │
│  Injects catalog into LLM prompt as context         │
│  LLM reads story + catalog → identifies which       │
│  entities are needed (e.g. orders + order_items)    │
│  LLM resolves real S3 paths from catalog            │
│  LLM outputs complete ETLSpec with real column names│
│                                                     │
│  CATALOG CHECK #1: "What data exists and where?"   │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  Node 2: resolve_catalog                            │
│  Looks up etl_spec.source.path in Glue by matching  │
│  against StorageDescriptor.Location                 │
│  Retrieves full column schema → stores as           │
│  source_schema in GraphState                        │
│  If not found → source_schema = None (fallback)    │
│                                                     │
│  CATALOG CHECK #2: "What are the exact columns?"   │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  Node 3: generate_code                              │
│  CodingAgent receives ETLSpec + source_schema       │
│  LLM generates PySpark using REAL column names      │
│  from the Glue catalog (grounded code generation)  │
└─────────────────────────────────────────────────────┘
        │
        ▼
  run_tests → approval_gate → create_pr → deploy
```

### Why twice?

- **Check #1 (parse_story)** resolves *which* datasets and *where* they are. The LLM needs the full catalog context to make that decision from the story text alone.
- **Check #2 (resolve_catalog)** retrieves the *detailed schema* for the specific source chosen in Check #1. This schema is passed into the code generation prompt so the LLM uses exact column names.

Separating them keeps each node's responsibility narrow and testable.

### Fallback (if catalog is empty or entity not found)

- Check #1 fallback: if `list_entities()` returns an empty list, the prompt tells the LLM "no entities registered — make reasonable assumptions and add a comment in the code."
- Check #2 fallback: if the source path is not in Glue, `source_schema = None`. The code generator prompt then instructs the LLM to note that column names are assumed.
- No pyarrow. No csv parsing. No DuckDB. Fallback is simply `None`.

---

## 4. Source Data: Olist — All 9 Tables

### S3 Layout

Upload Olist CSV files (as-is, no conversion) to:

```
s3://etl-agent-raw-prod/olist/orders/                  olist_orders_dataset.csv
s3://etl-agent-raw-prod/olist/order_items/             olist_order_items_dataset.csv
s3://etl-agent-raw-prod/olist/order_payments/          olist_order_payments_dataset.csv
s3://etl-agent-raw-prod/olist/order_reviews/           olist_order_reviews_dataset.csv
s3://etl-agent-raw-prod/olist/customers/               olist_customers_dataset.csv
s3://etl-agent-raw-prod/olist/sellers/                 olist_sellers_dataset.csv
s3://etl-agent-raw-prod/olist/products/                olist_products_dataset.csv
s3://etl-agent-raw-prod/olist/geolocation/             olist_geolocation_dataset.csv
s3://etl-agent-raw-prod/olist/product_category_translation/  product_category_name_translation.csv
```

### Glue Table Schemas (auto-detected by Crawler, shown for reference)

| Glue Entity | Key Columns | Typical Use |
|---|---|---|
| `orders` | order_id (string), customer_id (string), order_status (string), order_purchase_timestamp (timestamp), order_approved_at (timestamp), order_delivered_carrier_date (timestamp), order_delivered_customer_date (timestamp), order_estimated_delivery_date (timestamp) | Time-series, delivery SLA analysis |
| `order_items` | order_id (string), order_item_id (int), product_id (string), seller_id (string), shipping_limit_date (timestamp), price (double), freight_value (double) | Revenue aggregation, seller analysis |
| `order_payments` | order_id (string), payment_sequential (int), payment_type (string), payment_installments (int), payment_value (double) | Payment analysis, instalment patterns |
| `order_reviews` | review_id (string), order_id (string), review_score (int), review_comment_title (string), review_comment_message (string), review_creation_date (timestamp), review_answer_timestamp (timestamp) | Sentiment, satisfaction scoring |
| `customers` | customer_id (string), customer_unique_id (string), customer_zip_code_prefix (string), customer_city (string), customer_state (string) | Geographic segmentation, RFM |
| `sellers` | seller_id (string), seller_zip_code_prefix (string), seller_city (string), seller_state (string) | Seller performance analysis |
| `products` | product_id (string), product_category_name (string), product_name_lenght (int), product_description_lenght (int), product_photos_qty (int), product_weight_g (double), product_length_cm (double), product_height_cm (double), product_width_cm (double) | Category analysis, logistics |
| `geolocation` | geolocation_zip_code_prefix (string), geolocation_lat (double), geolocation_lng (double), geolocation_city (string), geolocation_state (string) | Geo enrichment, mapping |
| `product_category_translation` | product_category_name (string), product_category_name_english (string) | Internationalisation, labelling |

---

## 5. Infrastructure Changes (Terraform)

### New file: `infra/terraform/glue.tf`

Contains three resources:

**1. Glue Catalog Database**
```hcl
resource "aws_glue_catalog_database" "etl_agent_catalog" {
  name        = var.glue_catalog_database
  description = "ETL Agent data model — auto-populated by Glue Crawler"
  tags        = { Project = var.project_name }   # ← required; all resources must be tagged
}
```

**2. Glue Crawler IAM Role** (separate from ECS task role)
- Trust policy: `glue.amazonaws.com`
- S3 read — two separate statements with a prefix condition on `ListBucket` for least-privilege:
  ```
  Statement 1:
    Action:   s3:GetObject
    Resource: arn:aws:s3:::${var.s3_bucket}/olist/*     ← object ARN (path-scoped)

  Statement 2:
    Action:    s3:ListBucket
    Resource:  arn:aws:s3:::${var.s3_bucket}             ← bucket ARN (no path suffix)
    Condition: StringLike { "s3:prefix": ["olist/*", "olist/"] }
               ↑ restricts listing to the olist/ prefix only; without this the Crawler
                 can list all objects in the entire bucket
  ```
- The Glue Crawler IAM role must include `tags = { Project = var.project_name }` (all resources in this project are tagged)
- Glue catalog write permission — `CreateTable` and `UpdateTable` only; **do NOT add `CreateDatabase`** — Terraform creates the database via `aws_glue_catalog_database`, so the Crawler never needs to create databases:
  ```
  Actions:  glue:CreateTable, glue:UpdateTable
  Resource:
    arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog
    arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database}
    arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database}/*
  ```
  `data.aws_caller_identity.current` is already declared in `main.tf` — do not re-declare it in `glue.tf`

**3. Glue Crawler**
- Name: `"${var.project_name}-olist-crawler"` — never hardcode `etl-agent-olist-crawler`; every Terraform resource in this project uses the `${var.project_name}-xxx` prefix convention
- S3 target: `"s3://${var.s3_bucket}/olist/"` — reference the variable, not a literal bucket name
- **`var.s3_bucket` must be set correctly at `terraform apply` time.** `main.tf` creates the raw bucket as `"${var.project_name}-raw-${var.environment}"` (e.g. `etl-agent-raw-production`). `var.s3_bucket` has no default (it is declared `type = string` with no `default` in `ecs_variables.tf`). You must set it in `terraform.tfvars` or via `-var s3_bucket=etl-agent-raw-production`. If `var.s3_bucket` is set to a different value, the Crawler will point at the wrong bucket and find no CSVs.
- Database: `aws_glue_catalog_database.etl_agent_catalog.name` — reference the Terraform resource, not the literal string `"etl_agent_catalog"`; keeps it DRY if the variable default ever changes
- Table grouping: one Glue table per S3 sub-prefix (one per Olist CSV)
- Triggered on-demand (not scheduled — portfolio project)
- `depends_on = [aws_glue_catalog_database.etl_agent_catalog]` — **required**; without this, Terraform may attempt to create the Crawler before the database exists (Terraform parallelises resource creation by default and the Crawler's database name reference is a string, not a resource reference, so Terraform cannot infer the dependency)
- `tags = { Project = var.project_name }` — required; all resources must be tagged for cost allocation

### Modified: `infra/terraform/ecs_iam.tf`

Add **two** new inline policies to the **ECS task role**:

**Policy 1 — Output bucket write access:**

The existing `ecs_task_s3` policy grants S3 read/write only on `var.s3_bucket`. The processed/output bucket (`aws_s3_bucket.processed`) is a **different bucket** already managed by Terraform in `main.tf` as `"${var.project_name}-processed-${var.environment}"`. Without an explicit IAM grant, any pipeline that writes there will fail with `AccessDenied` at runtime.

> **Simplification vs earlier draft:** `main.tf` already declares `aws_s3_bucket.processed`. Reference it **directly** rather than adding two new variables (`output_data_bucket` and `output_data_bucket_name`). This keeps the config DRY and eliminates the risk of the variables being set to the wrong bucket name.

```hcl
resource "aws_iam_role_policy" "ecs_task_output_s3" {
  name = "s3-output-bucket"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject",
                    "s3:PutObjectTagging"]
        Resource = "arn:aws:s3:::${aws_s3_bucket.processed.bucket}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = "arn:aws:s3:::${aws_s3_bucket.processed.bucket}"
      }
    ]
  })
}
```

No `count` condition needed — the processed bucket always exists (it is declared unconditionally in `main.tf`).

**Policy 2 — Glue read/write access** (originally planned):

Add one new inline policy to the **ECS task role**:

```
Actions:
  glue:GetDatabase    ← DataCatalogClient.list_entities() uses this to validate DB exists
  glue:GetTable       ← DataCatalogClient.get_entity() and get_entity_by_path()
  glue:GetTables      ← DataCatalogClient.list_entities()
  glue:CreateTable    ← catalog admin API POST /api/v1/catalog
  glue:UpdateTable    ← catalog admin API PUT  /api/v1/catalog/{name}
  glue:DeleteTable    ← catalog admin API DELETE /api/v1/catalog/{name}

  ← NO glue:CreateDatabase — Terraform owns the database lifecycle; the runtime
     application never needs to create databases

Resource (scoped — never use "*"):
  arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog
  arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database}
  arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database}/*
```

`data.aws_caller_identity.current` is already declared in `main.tf` — do not re-declare it here.

### Modified: `infra/terraform/vpc.tf`

Add a VPC Interface Endpoint for the AWS Glue API. ECS tasks run in **private subnets** (no internet-facing IP). Without a Glue VPC endpoint, every `boto3.client("glue").get_tables()` call from a container will exit the VPC through the NAT Gateway, traverse the public internet, and return — incurring NAT data-transfer cost and breaking the "all AWS traffic stays within the AWS network" principle that the rest of the VPC is designed for. The existing `vpc.tf` already has five interface endpoints (SQS, ECR API, ECR DKR, CloudWatch Logs, SecretsManager) for exactly this reason. Glue must be added as a sixth:

```hcl
resource "aws_vpc_endpoint" "glue" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.glue"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${var.project_name}-glue-endpoint", Project = var.project_name }
}
```

The existing `aws_security_group.vpc_endpoints` already allows HTTPS (443) inbound from `aws_security_group.ecs_tasks` — no security group changes needed.

### Modified: `infra/terraform/ecs.tf`

Add to `common_env`:

```hcl
{ name = "GLUE_CATALOG_DATABASE", value = var.glue_catalog_database },
{ name = "OUTPUT_DATA_BUCKET",    value = "s3://${aws_s3_bucket.processed.bucket}/" },
```

`OUTPUT_DATA_BUCKET` references `aws_s3_bucket.processed` directly (the bucket managed in `main.tf`) rather than a separate variable. This keeps the `s3://` URI format the Python code expects and stays in sync with Terraform's resource graph automatically.

### Modified: `infra/terraform/ecs_variables.tf`

Add **one** variable (not three — see the ecs.tf and ecs_iam.tf notes above for why `output_data_bucket` and `output_data_bucket_name` are dropped):

```hcl
variable "glue_catalog_database" {
  description = "Name of the AWS Glue catalog database"
  type        = string
  default     = "etl_agent_catalog"
}
```

`OUTPUT_DATA_BUCKET` is computed directly from `aws_s3_bucket.processed.bucket` in `ecs.tf` and the IAM policy references it the same way. No separate variable needed.

### Modified: `infra/ecs-task-def-worker.json`

Add these two entries to the `environment` array (plain env vars, not secrets — same pattern as the existing `AWS_REGION` entry):

```json
{ "name": "GLUE_CATALOG_DATABASE", "value": "etl_agent_catalog" },
{ "name": "OUTPUT_DATA_BUCKET",    "value": "s3://etl-agent-processed-production/" }
```

`GLUE_CATALOG_DATABASE` defaults to `"etl_agent_catalog"` to match `var.glue_catalog_database`. `OUTPUT_DATA_BUCKET` is `"s3://etl-agent-processed-production/"` — this matches `aws_s3_bucket.processed.bucket` which resolves to `"${var.project_name}-processed-${var.environment}"` = `"etl-agent-processed-production"` using the default variable values. The static task def is used by the CD pipeline when Terraform is not directly involved in task registration; its value should match what `ecs.tf` computes.

---

## 6. Application Code Changes

### New file: `src/etl_agent/core/data_catalog.py`

A thin boto3 wrapper around the AWS Glue API. Contains:

- `DataField` — Pydantic model: `name: str`, `type: str`
- `DataEntity` — Pydantic model: `name`, `display_name`, `description`, `s3_path`, `format`, `columns: list[DataField]`, `data_classification`
- `DataCatalogClient` — class with methods:
  - `list_entities() -> list[DataEntity]` — calls `glue.get_tables(DatabaseName=self._db)`
  - `get_entity(name) -> DataEntity | None` — calls `glue.get_table(DatabaseName=self._db, Name=name)`
  - `get_entity_by_path(s3_path) -> DataEntity | None` — matches `StorageDescriptor.Location`
  - `create_entity(entity) -> None` — calls `glue.create_table()`
  - `update_entity(entity) -> None` — calls `glue.update_table()`
  - `delete_entity(name) -> None` — calls `glue.delete_table()`
  - `self._db` is set in `__init__` from `get_settings().glue_catalog_database` — **never hardcode `"etl_agent_catalog"` as a string literal inside the client**; the string `"etl_agent_catalog"` must only appear as the default value in `config.py` and `ecs_variables.tf`
- `get_catalog() -> DataCatalogClient` — cached singleton (uses `@lru_cache` on the module-level function)

### Modified: `pyproject.toml`

Two changes required:

**1. Add `boto3-stubs[glue]` to dev dependencies** — `data_catalog.py` uses `boto3.client("glue")`. The existing dev deps include `boto3-stubs[s3]` but not Glue stubs. Both `[project.optional-dependencies].dev` and `[tool.uv].dev-dependencies` must be updated (both sections exist and must stay in sync):

```toml
"boto3-stubs[s3,glue]>=1.35.0",   # replace the existing boto3-stubs[s3] entry in both sections
```

**2. Add `etl_agent.core.data_catalog` to the relaxed mypy overrides** — `src/etl_agent/core/` is NOT currently in the relaxed `[[tool.mypy.overrides]]` block. Under strict mode, any unresolved Glue stub type would cause a mypy error that blocks CI. Add `"etl_agent.core.data_catalog"` to the existing relaxed overrides module list in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = [
    "etl_agent.agents.*",
    "etl_agent.worker",
    "etl_agent.api.*",
    "etl_agent.core.audit",
    "etl_agent.core.llm_governance",
    "etl_agent.core.data_catalog",    # ← add this
    "etl_agent.database.*",
    ...
]
```

### Modified: `src/etl_agent/core/config.py`

Add two settings:

```python
glue_catalog_database: str = "etl_agent_catalog"
output_data_bucket: str = ""   # e.g. "s3://etl-agent-processed/"
```

### Modified: `src/etl_agent/core/models.py`

**Change 1:** `UserStory.source` and `UserStory.target` become optional:

```python
source: DataSource | None = None
target: DataSource | None = None
```

This is backward-compatible — the internal pipeline never reads `story.source` directly (it reads `etl_spec.source` which the story parser populates from the Glue catalog).

**Change 2:** Add `UserStoryRequest` — the public-facing model:

```python
class UserStoryRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1, max_length=2000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def validate_criteria(cls, v: list[Any]) -> list[Any]:
        for item in v:
            if len(str(item)) > 500:
                raise ValueError("Each acceptance criterion must be 500 characters or fewer.")
        return v
```

The `max_length=20` limit and per-item 500-char validator mirror the identical constraints on `UserStory.acceptance_criteria`. Omitting them would allow a user to submit a request that passes `UserStoryRequest` validation but then fails (or silently truncates) when the internal `UserStory` is constructed from it.

### New file: `src/etl_agent/api/v1/catalog.py`

REST router for catalog management. Primarily for admins to view and add business metadata on top of what the Glue Crawler auto-populated (descriptions, tags, classification).

```
GET    /api/v1/catalog              List all registered Glue entities
GET    /api/v1/catalog/{name}       Get one entity with full schema
POST   /api/v1/catalog              Create / register a new entity
PUT    /api/v1/catalog/{name}       Update description, tags, classification
DELETE /api/v1/catalog/{name}       Remove entity from Glue catalog
```

### Modified: `src/etl_agent/api/main.py`

Register the catalog router under `/api/v1`.

### Modified: `src/etl_agent/api/v1/stories.py`

**Import change at line 20** — add `UserStoryRequest` to the existing import:
```python
# BEFORE:
from etl_agent.core.models import RunStatus, UserStory
# AFTER:
from etl_agent.core.models import RunStatus, UserStory, UserStoryRequest
```
Without this, the endpoint type annotation and the internal constructor call both fail at import time.

- Accept `UserStoryRequest` instead of `UserStory` at `POST /api/v1/stories`
- Auto-generate `id = str(uuid4())`
- Build minimal internal `UserStory` from the request (source=None, target=None, default classification=internal):
  ```python
  internal_story = UserStory(
      id=str(uuid4()),
      title=story.title,
      description=story.description,
      acceptance_criteria=story.acceptance_criteria,
  )
  ```
  (`source`, `target` are `None` by default after the models.py change; `data_classification` defaults to `DataClassification.internal`; `tags` defaults to `[]`)
- Add `None` guards in **two places** where `story.source` / `story.target` are accessed:

  **Place 1 — `_persist_user_story()`** (writes to `UserStoryRecord`):
  All five field accesses on lines 45–49 need guards — not just three:
  ```python
  source_path   = story.source.path   if story.source else None
  source_format = story.source.format if story.source else None
  target_path   = story.target.path   if story.target else None
  target_format = story.target.format if story.target else None
  target_mode   = story.target.mode   if story.target else None
  ```

  **Place 2 — audit event payload** (the `log_event()` call immediately after `_persist_user_story()` in `submit_story()`). The payload dict currently contains direct attribute access:
  ```python
  # BEFORE (crashes when source/target are None):
  "source_path": story.source.path,
  "target_path": story.target.path,

  # AFTER (safe):
  "source_path": story.source.path if story.source else None,
  "target_path": story.target.path if story.target else None,
  ```
  Both locations must be fixed or the endpoint will raise `AttributeError: 'NoneType' object has no attribute 'path'` on every simplified story submission.

No DB migration required — `source_path`, `source_format`, `target_path`, `target_format`, `target_mode` columns in `UserStoryRecord` are already defined without `nullable=False` (they accept NULL).

### Modified: `src/etl_agent/agents/story_parser.py`

`StoryParserAgent.run()` gets two steps before building the prompt.

**Required import addition** — add to the top of `agents/story_parser.py`:
```python
from etl_agent.core.data_catalog import DataEntity, get_catalog
```
`DataEntity` is needed for the type annotation in the local variable; `get_catalog` is needed to call the Glue API. Without this import the module fails at runtime.

New logic in `run()`:

1. Call `get_catalog().list_entities()` to fetch all Glue entities
2. Pass the entity list to `build_story_parser_prompt(story, catalog_entities, self.settings.output_data_bucket)`

The third argument `self.settings.output_data_bucket` uses the new Settings field added in `config.py`. `self.settings` is already set in `__init__` via `self.settings = get_settings()`.

If the Glue call fails (permissions, network), catch the exception, log a warning, and pass `catalog_entities=[]` — the LLM falls back to assumption-based generation without crashing the pipeline.

### Modified: `src/etl_agent/prompts/story_parser.py`

Complete rewrite. Import changes:
- **Remove `import yaml`** — the current file uses `yaml.dump(story.model_dump())` to serialise the story into the prompt. After the rewrite the prompt is plain text (not YAML), so `import yaml` becomes unused and ruff will raise F401. Remove it.
- **Add `from etl_agent.core.data_catalog import DataEntity`** — the new signature uses `DataEntity` in its parameter list; without this import the module fails to load.
- Keep `from etl_agent.core.models import UserStory` — still needed for the type annotation.
- Keep `from etl_agent.prompts.examples.story_parser_examples import STORY_PARSER_EXAMPLES` — the few-shot examples are still used in the new prompt.

New function signature — **three parameters** (not the old one):

```python
def build_story_parser_prompt(
    story: UserStory,
    catalog_entities: list[DataEntity],
    output_data_bucket: str,          # ← third parameter, NOT accessed via get_settings()
) -> str:
```

`output_data_bucket` must be passed in as a parameter, not fetched with `get_settings()` inside the function. Prompt functions in this project are pure string builders — they receive all values as arguments (see `build_code_generator_prompt` in `prompts/code_generator.py` which receives `etl_spec`, `previous_failure`, `retry_count`, `source_schema` as parameters). This makes them testable without environment setup.

The caller (`StoryParserAgent.run()`) fetches it: `self.settings.output_data_bucket`.

If `output_data_bucket` is empty, the prompt must tell the LLM explicitly: "No output bucket is configured — use a reasonable S3 path assumption and add a comment."

New prompt structure:
1. System context: "You are a Data Engineering architect..."
2. **Available Data Entities section** — lists all 9 Olist tables with their S3 paths, format, and columns. If list is empty: "No entities registered — make reasonable assumptions."
3. **Output Bucket** — the `output_data_bucket` parameter; if empty, state that in the prompt
4. **Instructions** — select source entity/entities from the catalog; for target, either pick an existing entity or construct `{output_data_bucket}{pipeline_name}/`; output complete ETLSpec JSON
5. **User Story** — title, description, acceptance criteria (plain text, no YAML dump)
6. **Required JSON schema** — same ETLSpec structure as before

### Modified: `src/etl_agent/prompts/examples/story_parser_examples.py`

Rewrite both examples to match the new format:
- Input: title + description + acceptance criteria + catalog context (Olist entities)
- Output: ETLSpec JSON with real Olist column names and S3 paths resolved from catalog

### Modified: `src/etl_agent/agents/orchestrator.py`

**Rename** `_node_infer_schema` → `_node_resolve_catalog`. The entire function body is replaced — the local import, the docstring, and all logic:

```
OLD (deleted entirely):
  from etl_agent.tools.aws_tools import infer_schema_from_s3   ← local import, gone
  source_fmt = etl_spec.source.format                           ← unused in new node, gone
  schema = infer_schema_from_s3(source_path, source_fmt)        ← gone

NEW logic:
  1. Get etl_spec.source.path from GraphState  (source_path only — format not needed)
  2. Call get_catalog().get_entity_by_path(source_path)
  3. If found → build source_schema dict from entity.columns
  4. If not found → source_schema = None (LLM makes assumptions)
  5. Return {"source_schema": schema, "current_stage": "resolve_catalog"}
```

**Do NOT declare `source_fmt`** in the new function — it is unused in the Glue lookup and ruff will raise F841 (local variable assigned to but never used).

**Update module-level docstring** at the top of the file. The graph topology comment currently says:
```
infer_schema   ← reads parquet/delta metadata from S3 (graceful fallback)
```
Change it to:
```
resolve_catalog ← looks up source entity schema in AWS Glue Data Catalog
```

Graph wiring: node registration and edges change from `"infer_schema"` to `"resolve_catalog"`. The `current_stage` stored in the DB changes from `"infer_schema"` to `"resolve_catalog"` (free-text string column, no migration needed).

### Modified: `src/etl_agent/tools/aws_tools.py`

**Delete:**
- `infer_schema_from_s3()` — pyarrow-based, parquet-only
- `_read_parquet_schema()` — pyarrow-based
- `import contextlib` at the top of the file — this import was added solely for `infer_schema_from_s3()` (used inside `contextlib.suppress` blocks at lines 330 and 352). Once both functions are deleted, `import contextlib` becomes an unused import and ruff will raise F401. It must be removed alongside the functions.

**No replacement needed.** The fallback in `_node_resolve_catalog` is simply `source_schema = None`. pyarrow is no longer used anywhere in the agent code (it can remain in `pyproject.toml` as a data dependency for generated PySpark pipelines).

### Modified: `src/etl_agent/static/index.html`

> **Important path correction:** `api/main.py` mounts `src/etl_agent/static/` (not `src/etl_agent/ui/`) at `/ui`. The file at `src/etl_agent/static/index.html` is the one actually served. The files under `src/etl_agent/ui/` (including `ui/templates/index.html` and `ui/static/app.js`) are NOT mounted and are not reachable by the browser. All UI changes go into `src/etl_agent/static/index.html` only.
>
> `src/etl_agent/static/index.html` is self-contained — all JavaScript is inline (no separate `app.js`). There is no `app.js` in the `static/` directory, so no separate JS file needs to be created or modified.

Changes to `src/etl_agent/static/index.html`:

- Replace the YAML/JSON textarea with three plain fields:
  - `<input>` for title
  - `<textarea>` for description
  - `<textarea>` for acceptance criteria (one criterion per line → split into list on submit)
- Remove all YAML example snippets from the inline JS
- Remove YAML parsing logic from the inline `submitStory()` function
- Update `submitStory()` to POST:
  ```json
  {
    "title": "...",
    "description": "...",
    "acceptance_criteria": ["criterion 1", "criterion 2"]
  }
  ```
- Add a **Catalog** tab that calls `GET /api/v1/catalog` and displays the 9 Olist entities with their schemas, so users know what data is available before writing a story
- Add inline `loadCatalog()` function that fetches `GET /api/v1/catalog` and renders entities in the Catalog tab

---

## 7. Previously Implemented — Kept As-Is

The following was already implemented in earlier sessions and integrates cleanly with this plan:

| File | What was done | Status |
|---|---|---|
| `src/etl_agent/core/state.py` | Added `source_schema: dict[str, Any] \| None` to GraphState | Keep — used by `_node_resolve_catalog` and coding agent |
| `src/etl_agent/prompts/code_generator.py` | Added `source_schema` parameter; injects grounded schema section into LLM prompt | Keep — unchanged |
| `src/etl_agent/agents/coding_agent.py` | Passes `state.get("source_schema")` to prompt builder | Keep — unchanged |
| `src/etl_agent/agents/orchestrator.py` | Added `_node_infer_schema` between `parse_story` and `generate_code` | Will be renamed to `_node_resolve_catalog` and logic replaced |

---

## 8. Pre-existing IAM Issues to Fix in `ecs_iam.tf`

While reviewing for broad permissions, two issues were found in the existing file that should be fixed in the same PR:

**Issue 1 — `ecs_task_ecr` policy uses `Resource = "*"` for all ECR actions:**

```hcl
# CURRENT (too broad):
Action   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability",
             "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
Resource = "*"

# FIX — split into two statements:
# Statement 1: GetAuthorizationToken requires "*" (AWS account-level API, no resource restriction possible)
Action   = ["ecr:GetAuthorizationToken"]
Resource = "*"

# Statement 2: repository-level actions scoped to the specific repo (same pattern as iam.tf)
Action   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
Resource = "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}-app"
```

**Issue 2 — `ecs_execution_secrets` KMS policy — already acceptable:** `kms:Decrypt` with `Resource = "*"` is the correct pattern here because KMS key ARNs are not known at policy write time. The `Condition` block constraining it to `kms:ViaService = "secretsmanager.${var.aws_region}.amazonaws.com"` is the AWS-recommended approach. No change needed.

**Issue 3 — `ecs_task_cloudwatch` — already acceptable:** `cloudwatch:PutMetricData` does not support resource-level restrictions (AWS limitation). The `Condition` block limiting it to the `ETLAgent` namespace is the correct mitigation. No change needed.

---

## 9. What Does NOT Change (Unchanged Code)

- `ETLSpec`, `TestResult`, `RunResult` Pydantic models
- All downstream agents: `CodingAgent`, `TestAgent`, `PRAgent`, `DeployAgent`
- SQS/ECS worker pipeline, Fargate deployment
- GitHub PR creation, S3 artifact upload
- All previously fixed bugs: PENDING status, dry-run, commit message length, secret injection
- `UserStoryRecord` DB table — no migration needed (source/target columns already nullable)

---

## 10. Complete File Change Summary

| File | Type | Area |
|---|---|---|
| `infra/terraform/glue.tf` | **NEW** | Glue database + Crawler + Crawler IAM role |
| `infra/terraform/vpc.tf` | **MODIFY** | Add VPC Interface Endpoint for AWS Glue |
| `infra/terraform/ecs_iam.tf` | **MODIFY** | Add ECS task Glue policy; output-bucket S3 policy; fix ECR `Resource = "*"` |
| `infra/terraform/ecs.tf` | **MODIFY** | Add `GLUE_CATALOG_DATABASE`, `OUTPUT_DATA_BUCKET` to `common_env` |
| `infra/terraform/ecs_variables.tf` | **MODIFY** | Add `glue_catalog_database` variable (output bucket vars dropped — reference `aws_s3_bucket.processed` directly) |
| `pyproject.toml` | **MODIFY** | Add `boto3-stubs[glue]` to dev deps; add `data_catalog` to relaxed mypy overrides |
| `infra/ecs-task-def-worker.json` | **MODIFY** | Add `GLUE_CATALOG_DATABASE`, `OUTPUT_DATA_BUCKET` to `environment` |
| `src/etl_agent/core/config.py` | **MODIFY** | Add `glue_catalog_database`, `output_data_bucket` settings |
| `src/etl_agent/core/data_catalog.py` | **NEW** | DataField, DataEntity, DataCatalogClient, get_catalog() |
| `src/etl_agent/core/models.py` | **MODIFY** | source/target optional; add UserStoryRequest |
| `src/etl_agent/tools/aws_tools.py` | **MODIFY** | Delete infer_schema_from_s3(), _read_parquet_schema() |
| `src/etl_agent/api/v1/catalog.py` | **NEW** | Catalog CRUD API router |
| `src/etl_agent/api/v1/stories.py` | **MODIFY** | Accept UserStoryRequest; None guards for source/target |
| `src/etl_agent/api/main.py` | **MODIFY** | Register catalog router |
| `src/etl_agent/agents/story_parser.py` | **MODIFY** | Fetch catalog entities; pass to prompt builder |
| `src/etl_agent/prompts/story_parser.py` | **MODIFY** | Full rewrite with catalog context + new signature |
| `src/etl_agent/prompts/examples/story_parser_examples.py` | **MODIFY** | Rewrite examples using Olist entities |
| `src/etl_agent/agents/orchestrator.py` | **MODIFY** | Rename + replace infer_schema → resolve_catalog (Glue lookup) |
| `src/etl_agent/static/index.html` | **MODIFY** | 3-field form + Catalog tab (self-contained; all JS inline — no separate app.js) |

---

## 11. One-Time Setup Steps (After Deployment, Before Testing)

> **Note on resource names:** The commands below use the default `var.project_name = "etl-agent"` and `var.environment = "production"`. If you changed those Terraform variable defaults, substitute accordingly (e.g. the crawler name is `{project_name}-olist-crawler`, the S3 bucket is `{project_name}-raw-{environment}`).

```bash
# Step 1 — Upload Olist CSV files to S3 (run from your laptop once)
aws s3 cp olist_orders_dataset.csv              s3://etl-agent-raw-production/olist/orders/
aws s3 cp olist_order_items_dataset.csv         s3://etl-agent-raw-production/olist/order_items/
aws s3 cp olist_order_payments_dataset.csv      s3://etl-agent-raw-production/olist/order_payments/
aws s3 cp olist_order_reviews_dataset.csv       s3://etl-agent-raw-production/olist/order_reviews/
aws s3 cp olist_customers_dataset.csv           s3://etl-agent-raw-production/olist/customers/
aws s3 cp olist_sellers_dataset.csv             s3://etl-agent-raw-production/olist/sellers/
aws s3 cp olist_products_dataset.csv            s3://etl-agent-raw-production/olist/products/
aws s3 cp olist_geolocation_dataset.csv         s3://etl-agent-raw-production/olist/geolocation/
aws s3 cp product_category_name_translation.csv s3://etl-agent-raw-production/olist/product_category_translation/

# Step 2 — Run the Glue Crawler (auto-populates all 9 Glue tables)
# Crawler name = ${var.project_name}-olist-crawler (defaults to etl-agent-olist-crawler)
aws glue start-crawler --name etl-agent-olist-crawler

# Step 3 — Verify all 9 tables appeared in the catalog
aws glue get-tables --database-name etl_agent_catalog \
  --query 'TableList[].Name' --output table

# Step 4 — (Optional) Add business descriptions via admin API
curl -s -X PUT https://<your-alb>/api/v1/catalog/orders \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"description": "Customer order transactions 2016-2018 from Olist marketplace"}'
```

---

## 12. Example User Story (After Implementation)

**Before (what users had to type):**
```yaml
id: monthly-revenue
title: Monthly Revenue by Category
description: Aggregate monthly revenue by product category
source:
  path: s3://etl-agent-raw-prod/olist/order_items/
  format: csv
target:
  path: s3://etl-agent-processed/monthly_revenue/
  format: delta
transformations:
  - operation: join
    description: Join with products to get category
  - operation: aggregate
    description: Sum price by month and category
```

**After (what users type):**
```
Title: Monthly Revenue by Product Category

Description: Calculate total monthly revenue broken down by product category.
Join order items with product data to get the category name.

Acceptance Criteria:
- Output contains columns: year, month, product_category_name_english, total_revenue
- Covers all completed orders only
- Partitioned by year and month
```

The agent resolves `order_items` and `products` from the catalog, joins them using real column names (`product_id`, `product_category_name`), joins with `product_category_translation` for English names, and writes the output to `{output_data_bucket}monthly_revenue_by_category/`.

---

## 13. Decisions Log

| Decision | Alternatives Considered | Reason Chosen |
|---|---|---|
| AWS Glue Data Catalog | Local JSON file, DynamoDB | Purpose-built for this; AWS Console visible; crawler integration |
| Glue Crawler for schema discovery | pyarrow (parquet only), boto3+csv module, DuckDB | Zero code; AWS-native; works with CSV as-is; format-agnostic |
| CSV files in S3 (no conversion) | Convert to parquet | No conversion overhead; Glue Crawler handles CSV natively |
| Olist dataset | Amazon Reviews, NYC Taxi | 9 related tables; enables joins, aggregations, RFM; matches story examples |
| Catalog checked twice (parse + resolve) | Checked once only | Separation of concerns: parse selects entities, resolve fetches schema |
| Fallback = None (no custom inference) | boto3+csv, DuckDB | Simplest correct behaviour; Glue covers all registered data |
