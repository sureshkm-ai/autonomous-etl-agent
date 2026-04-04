# =============================================================================
# Glue — catalog database, crawler IAM role, olist crawler, and ETL IAM
#
# aws_caller_identity is declared in main.tf — do not re-declare here.
#
# Changes vs original:
#   - Crawler: replaced 9 hardcoded s3_target blocks with a single parent path
#   - Crawler: added daily 1AM schedule (nightly reconciliation)
#   - Crawler IAM: widened S3 read to cover all sub-prefixes under olist/
#   - Added aws_iam_role.glue_etl + inline policy for Iceberg ETL job
# =============================================================================

# ─── Glue Catalog Database ────────────────────────────────────────────────────

resource "aws_glue_catalog_database" "etl_agent_catalog" {
  name        = var.glue_catalog_database
  description = "ETL Agent data model — auto-registered by Lambda/Glue ETL + reconciled nightly by Crawler"
  tags        = { Project = var.project_name }
}

# ─── Glue Crawler IAM Role ────────────────────────────────────────────────────

resource "aws_iam_role" "glue_crawler" {
  name = "${var.project_name}-glue-crawler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project_name }
}

resource "aws_iam_role_policy" "glue_crawler_s3" {
  name = "s3-olist-read"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Object-level read — covers all datasets under olist/ (recursive)
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.s3_bucket}/olist/**"
      },
      {
        # Bucket-level list — restricted to olist/ prefix via condition
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.s3_bucket}"
        Condition = {
          StringLike = { "s3:prefix" = ["olist/*", "olist/"] }
        }
      }
    ]
  })
}

# AWSGlueServiceRole covers all Glue catalog actions (GetDatabase, GetTable,
# GetTables, CreateTable, UpdateTable, BatchCreatePartition, etc.) plus
# CloudWatch Logs — eliminating the need for separate inline policies for each.
resource "aws_iam_role_policy_attachment" "glue_crawler_service_role" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# ─── Glue Crawler ─────────────────────────────────────────────────────────────
# Single parent path replaces 9 hardcoded paths — automatically picks up new
# datasets added to olist/ without any Terraform change.
# Schedule: nightly 1AM UTC reconciliation (safety net only;
#   primary schema registration is done by the Lambda → ETL pipeline).

resource "aws_glue_crawler" "olist" {
  name          = "${var.project_name}-olist-crawler"
  role          = aws_iam_role.glue_crawler.arn
  database_name = aws_glue_catalog_database.etl_agent_catalog.name
  schedule      = "cron(0 1 * * ? *)"

  # One path covers all sub-prefixes (orders, customers, etc.)
  s3_target { path = "s3://${var.s3_bucket}/olist/" }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "DEPRECATE_IN_DATABASE"
  }

  tags = { Project = var.project_name }

  depends_on = [aws_glue_catalog_database.etl_agent_catalog]
}

# ─── Glue ETL Job IAM Role ────────────────────────────────────────────────────
# Used by the csv_to_iceberg Glue job (defined in iceberg.tf).
# Needs S3 read (raw bucket), S3 write (processed + artifacts), and Glue
# catalog access for Iceberg table registration.

resource "aws_iam_role" "glue_etl" {
  name = "${var.project_name}-glue-etl"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project_name }
}

resource "aws_iam_role_policy" "glue_etl_s3" {
  name = "s3-iceberg-rw"
  role = aws_iam_role.glue_etl.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read raw source data
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:HeadObject"]
        Resource = "arn:aws:s3:::${var.s3_bucket}/*"
      },
      {
        # List raw bucket
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.s3_bucket}"
      },
      {
        # Write Iceberg data files to processed bucket
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
        ]
        Resource = "arn:aws:s3:::${var.project_name}-processed-${var.environment}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.project_name}-processed-${var.environment}"
      },
      {
        # Glue temp dir in artifacts bucket
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.project_name}-artifacts-${var.environment}",
          "arn:aws:s3:::${var.project_name}-artifacts-${var.environment}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_etl_catalog" {
  name = "glue-catalog-iceberg"
  role = aws_iam_role.glue_etl.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "glue:GetDatabase", "glue:GetDatabases",
        "glue:GetTable", "glue:GetTables",
        "glue:CreateTable", "glue:UpdateTable",
        "glue:GetPartitions", "glue:BatchCreatePartition",
        "glue:BatchDeletePartition"
      ]
      Resource = [
        "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
        "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database}",
        "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database}/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_etl_service_role" {
  role       = aws_iam_role.glue_etl.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}
