terraform {
  required_version = ">= 1.9.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# ── S3 Buckets ────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "raw" {
  bucket = "${var.project_name}-raw-${var.environment}"
}

resource "aws_s3_bucket" "processed" {
  bucket = "${var.project_name}-processed-${var.environment}"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.project_name}-artifacts-${var.environment}"
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Block all public access on all buckets
resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "processed" {
  bucket                  = aws_s3_bucket.processed.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── S3 EventBridge Notification (raw bucket) ──────────────────────────────────
# Enables S3 to send all object-level events to EventBridge.
# The EventBridge rule in iceberg.tf filters for ObjectCreated only.
# NOTE: This requires the raw bucket to have EventBridge notifications enabled;
#       the actual rule/target live in iceberg.tf.

resource "aws_s3_bucket_notification" "raw_events" {
  bucket      = aws_s3_bucket.raw.id
  eventbridge = true
}

# ── SSH Key Pair ──────────────────────────────────────────────────────────────
# Removed: ECS Fargate does not use EC2 key pairs.
# The original resource has been preserved in ec2_bkp.tf.bak.
