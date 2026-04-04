# =============================================================================
# iceberg.tf — Event-driven schema detection + Iceberg conversion pipeline
#
# Resources created here:
#   1. EventBridge rule  — fires on every S3 ObjectCreated event on raw bucket
#   2. Lambda function   — schema_detector: reads file schema, triggers Glue ETL
#   3. Lambda IAM role   — minimal permissions for S3 read + Glue start_job_run
#   4. pyarrow Lambda layer (ZIP built by infra/lambda/schema_detector/build_layer.sh)
#   5. Glue ETL job      — csv_to_iceberg: reads raw CSV, writes Iceberg table
#   6. EventBridge → Lambda permission
#
# Depends on:
#   aws_s3_bucket.raw            (main.tf)
#   aws_s3_bucket.processed      (main.tf)
#   aws_s3_bucket.artifacts      (main.tf)
#   aws_glue_catalog_database    (glue.tf)
#   aws_iam_role.glue_etl        (glue.tf)
#   data.aws_caller_identity     (main.tf)
# =============================================================================

# ─── EventBridge rule: S3 ObjectCreated on raw bucket ────────────────────────

resource "aws_cloudwatch_event_rule" "s3_object_created" {
  name        = "${var.project_name}-s3-object-created"
  description = "Fires on every file upload to the raw S3 bucket"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.raw.bucket] }
    }
  })

  tags = { Project = var.project_name }
}

resource "aws_cloudwatch_event_target" "schema_detector" {
  rule      = aws_cloudwatch_event_rule.s3_object_created.name
  target_id = "schema-detector-lambda"
  arn       = aws_lambda_function.schema_detector.arn
}

# Allow EventBridge to invoke the Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.schema_detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.s3_object_created.arn
}

# ─── Lambda IAM Role ──────────────────────────────────────────────────────────

resource "aws_iam_role" "schema_detector_lambda" {
  name = "${var.project_name}-schema-detector"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project_name }
}

resource "aws_iam_role_policy" "schema_detector_s3" {
  name = "s3-schema-read"
  role = aws_iam_role.schema_detector_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:HeadObject"]
        # Lambda only needs to sample the file to read its schema
        Resource = "arn:aws:s3:::${aws_s3_bucket.raw.bucket}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${aws_s3_bucket.raw.bucket}"
      }
    ]
  })
}

resource "aws_iam_role_policy" "schema_detector_glue" {
  name = "glue-catalog-read-and-trigger"
  role = aws_iam_role.schema_detector_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["glue:GetTable", "glue:GetTables"]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database}",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun"]
        Resource = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job/${aws_glue_job.csv_to_iceberg.name}"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "schema_detector_basic_exec" {
  role       = aws_iam_role.schema_detector_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ─── pyarrow Lambda Layer ─────────────────────────────────────────────────────
# Build with:  cd infra/lambda/schema_detector && bash build_layer.sh
# The resulting pyarrow-layer.zip is committed to the repo (or stored in S3).

resource "aws_lambda_layer_version" "pyarrow" {
  layer_name          = "${var.project_name}-pyarrow"
  compatible_runtimes = ["python3.12"]
  filename            = "${path.module}/../../infra/lambda/pyarrow-layer.zip"

  # Update this hash whenever the layer ZIP is rebuilt
  # sha256 = filebase64sha256("${path.module}/../../infra/lambda/pyarrow-layer.zip")
}

# ─── Schema Detector Lambda Function ─────────────────────────────────────────

resource "aws_lambda_function" "schema_detector" {
  function_name = "${var.project_name}-schema-detector"
  description   = "Detects new/changed data schemas on S3 upload and triggers Glue ETL → Iceberg"

  runtime     = "python3.12"
  handler     = "handler.lambda_handler"
  role        = aws_iam_role.schema_detector_lambda.arn
  timeout     = 60      # schema reading rarely takes > 5s; 60s is generous
  memory_size = 256     # pyarrow needs ~100MB; 256 gives comfortable headroom

  # ZIP built from infra/lambda/schema_detector/ (handler + schema_reader + glue_helper)
  filename         = "${path.module}/../../infra/lambda/schema_detector.zip"
  source_code_hash = filebase64sha256("${path.module}/../../infra/lambda/schema_detector.zip")

  layers = [aws_lambda_layer_version.pyarrow.arn]

  environment {
    variables = {
      GLUE_DATABASE      = var.glue_catalog_database
      GLUE_JOB_NAME      = aws_glue_job.csv_to_iceberg.name
      PROCESSED_BUCKET   = aws_s3_bucket.processed.bucket
      RAW_BUCKET         = aws_s3_bucket.raw.bucket
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.schema_detector_basic_exec,
    aws_cloudwatch_log_group.schema_detector,
  ]

  tags = { Project = var.project_name }
}

# Pre-create the log group so Terraform controls its retention
resource "aws_cloudwatch_log_group" "schema_detector" {
  name              = "/aws/lambda/${var.project_name}-schema-detector"
  retention_in_days = 14
  tags              = { Project = var.project_name }
}

# ─── Glue ETL Job: CSV → Apache Iceberg ──────────────────────────────────────
# Script uploaded to S3 by the Makefile / CI pipeline.
# Run: aws s3 cp infra/glue_jobs/csv_to_iceberg.py s3://<artifacts-bucket>/glue-jobs/

resource "aws_glue_job" "csv_to_iceberg" {
  name         = "${var.project_name}-csv-to-iceberg"
  description  = "Converts raw CSV files to Apache Iceberg format and registers in Glue catalog"
  role_arn     = aws_iam_role.glue_etl.arn
  glue_version = "4.0"
  worker_type  = "G.1X"
  number_of_workers = 2
  timeout           = 60  # minutes

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.artifacts.bucket}/glue-jobs/csv_to_iceberg.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"            = "python"
    "--enable-glue-datacatalog" = "true"
    "--datalake-formats"        = "iceberg"
    "--conf"                    = "spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.processed.bucket}/iceberg/ --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions"
    "--TempDir"                 = "s3://${aws_s3_bucket.artifacts.bucket}/glue-tmp/"
    "--enable-metrics"          = "true"
    "--enable-continuous-cloudwatch-log" = "true"
  }

  execution_property {
    max_concurrent_runs = 10
  }

  tags = { Project = var.project_name }

  depends_on = [aws_iam_role.glue_etl]
}

# ─── Outputs ──────────────────────────────────────────────────────────────────

output "schema_detector_lambda_name" {
  description = "Name of the schema detector Lambda function"
  value       = aws_lambda_function.schema_detector.function_name
}

output "csv_to_iceberg_job_name" {
  description = "Name of the Glue CSV-to-Iceberg ETL job"
  value       = aws_glue_job.csv_to_iceberg.name
}

output "iceberg_warehouse_uri" {
  description = "S3 URI of the Iceberg warehouse (set as ICEBERG_WAREHOUSE env var in ECS)"
  value       = "s3://${aws_s3_bucket.processed.bucket}/iceberg/"
}
