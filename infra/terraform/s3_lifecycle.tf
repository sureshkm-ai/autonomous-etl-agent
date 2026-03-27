# S3 Lifecycle Configuration — data-classification-driven retention policies
#
# Each rule targets a specific data_classification tag value and enforces:
#   public / internal    → Intelligent-Tiering at 30d, expire at 365d
#   confidential         → Glacier at 30d, expire at 730d (2 years)
#   restricted           → Glacier at 7d,  expire at 2555d (7 years)
#
# The lifecycle rules complement the object tags written by aws_tools.py.

resource "aws_s3_bucket_lifecycle_configuration" "etl_agent_lifecycle" {
  bucket = aws_s3_bucket.artifacts.id

  # -------------------------------------------------------------------------
  # Rule 1: Public — lightweight tiering, annual expiry
  # -------------------------------------------------------------------------
  rule {
    id     = "public-data-lifecycle"
    status = "Enabled"

    filter {
      tag {
        key   = "data_classification"
        value = "public"
      }
    }

    transition {
      days          = 30
      storage_class = "INTELLIGENT_TIERING"
    }

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # -------------------------------------------------------------------------
  # Rule 2: Internal — same as public
  # -------------------------------------------------------------------------
  rule {
    id     = "internal-data-lifecycle"
    status = "Enabled"

    filter {
      tag {
        key   = "data_classification"
        value = "internal"
      }
    }

    transition {
      days          = 30
      storage_class = "INTELLIGENT_TIERING"
    }

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # -------------------------------------------------------------------------
  # Rule 3: Confidential — archive quickly, retain 2 years
  # -------------------------------------------------------------------------
  rule {
    id     = "confidential-data-lifecycle"
    status = "Enabled"

    filter {
      tag {
        key   = "data_classification"
        value = "confidential"
      }
    }

    transition {
      days          = 30
      storage_class = "GLACIER"
    }

    expiration {
      days = 730
    }

    noncurrent_version_expiration {
      noncurrent_days = 14
    }
  }

  # -------------------------------------------------------------------------
  # Rule 4: Restricted — archive immediately, retain 7 years (regulatory)
  # -------------------------------------------------------------------------
  rule {
    id     = "restricted-data-lifecycle"
    status = "Enabled"

    filter {
      tag {
        key   = "data_classification"
        value = "restricted"
      }
    }

    transition {
      days          = 7
      storage_class = "GLACIER"
    }

    expiration {
      days = 2555
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  # -------------------------------------------------------------------------
  # Rule 5: Abort incomplete multipart uploads (cannot be combined with tag
  # filters — AWS restriction). Applies to all objects in the bucket.
  # -------------------------------------------------------------------------
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {
      prefix = ""
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# -------------------------------------------------------------------------
# S3 bucket versioning — required for noncurrent_version_expiration rules
# -------------------------------------------------------------------------
resource "aws_s3_bucket_versioning" "etl_artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

# -------------------------------------------------------------------------
# S3 default server-side encryption
# -------------------------------------------------------------------------
resource "aws_s3_bucket_server_side_encryption_configuration" "etl_artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# -------------------------------------------------------------------------
# Block all public access
# -------------------------------------------------------------------------
resource "aws_s3_bucket_public_access_block" "etl_artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
