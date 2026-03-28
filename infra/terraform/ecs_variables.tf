# =============================================================================
# Variables — ECS Fargate architecture
# Set overrides in terraform.tfvars (never commit secrets).
# =============================================================================

# ─── Networking ───────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

# ─── Project ──────────────────────────────────────────────────────────────────

variable "project_name" {
  description = "Short identifier used as a prefix for all resources"
  type        = string
  default     = "etl-agent"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (production | staging)"
  type        = string
  default     = "production"
}

# ─── Container image ──────────────────────────────────────────────────────────
# ecs.tf resolves the image URI dynamically via data.aws_ecr_image,
# so no explicit image_tag variable is needed. Set this only to pin a tag.

variable "image_tag" {
  description = "Optional: pin to a specific ECR image tag. Defaults to latest digest."
  type        = string
  default     = ""
}

# ─── ECS scaling ─────────────────────────────────────────────────────────────

variable "api_desired_count" {
  description = "Initial number of API tasks"
  type        = number
  default     = 2
}

variable "api_min_count" {
  description = "Minimum API tasks (autoscaling floor)"
  type        = number
  default     = 1
}

variable "api_max_count" {
  description = "Maximum API tasks (autoscaling ceiling)"
  type        = number
  default     = 4
}

variable "worker_max_count" {
  description = "Maximum concurrent pipeline worker tasks"
  type        = number
  default     = 10
}

# ─── TLS ──────────────────────────────────────────────────────────────────────

variable "acm_certificate_arn" {
  description = "ARN of ACM certificate for the ALB HTTPS listener"
  type        = string
  default     = ""
}

# ─── RDS ──────────────────────────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.small"
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "etl_agent"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "etlagent"
}

variable "db_password" {
  description = "PostgreSQL master password — set via TF_VAR_db_password env var"
  type        = string
  sensitive   = true
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for RDS (recommended for production)"
  type        = bool
  default     = true
}

# ─── S3 ───────────────────────────────────────────────────────────────────────

variable "s3_bucket" {
  description = "S3 bucket for pipeline artifacts and ALB access logs"
  type        = string
}

# ─── Governance ───────────────────────────────────────────────────────────────

variable "cors_origins" {
  description = "Comma-separated CORS allowed origins (or * for all)"
  type        = string
  default     = "*"
}

variable "max_tokens_per_run" {
  description = "Per-run token budget cap"
  type        = number
  default     = 500000
}

variable "budget_approval_threshold_pct" {
  description = "Token budget % that triggers human approval gate"
  type        = number
  default     = 75
}

# ─── Alerting ─────────────────────────────────────────────────────────────────

variable "alarm_sns_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarms. Leave empty to disable."
  type        = string
  default     = ""
}
