# =============================================================================
# Glue — catalog database, crawler IAM role, and olist crawler
#
# aws_caller_identity is declared in main.tf — do not re-declare here.
# =============================================================================

# ─── Glue Catalog Database ────────────────────────────────────────────────────

resource "aws_glue_catalog_database" "etl_agent_catalog" {
  name        = var.glue_catalog_database
  description = "ETL Agent data model — auto-populated by Glue Crawler"
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
        # Object-level read — scoped to olist/ prefix only
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.s3_bucket}/olist/*"
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

resource "aws_iam_role_policy" "glue_crawler_catalog" {
  name = "glue-catalog-write"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # CreateTable + UpdateTable only — no CreateDatabase (Terraform owns DB lifecycle)
        Effect = "Allow"
        Action = ["glue:CreateTable", "glue:UpdateTable"]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database}",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database}/*",
        ]
      }
    ]
  })
}

# ─── Glue Crawler ─────────────────────────────────────────────────────────────

resource "aws_glue_crawler" "olist" {
  name          = "${var.project_name}-olist-crawler"
  role          = aws_iam_role.glue_crawler.arn
  database_name = aws_glue_catalog_database.etl_agent_catalog.name

  s3_target {
    path = "s3://${var.s3_bucket}/olist/"
  }

  # One Glue table per S3 sub-prefix (one per Olist CSV folder)
  configuration = jsonencode({
    Version = 1.0
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
  })

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "DEPRECATE_IN_DATABASE"
  }

  tags = { Project = var.project_name }

  # Ensure the catalog database exists before the Crawler is created.
  # Terraform parallelises resource creation; the database_name reference is a
  # string (not a resource reference) so Terraform cannot infer the dependency.
  depends_on = [aws_glue_catalog_database.etl_agent_catalog]
}
