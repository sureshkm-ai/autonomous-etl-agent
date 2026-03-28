# =============================================================================
# outputs.tf — legacy S3 / ECR outputs kept for backward compatibility.
#
# NOTE: The EC2 / EIP outputs that were here have been removed as part of the
#       ECS Fargate migration.  All new ECS, ALB, SQS, RDS, VPC, and IAM
#       outputs live in ecs_outputs.tf.
# =============================================================================

output "s3_raw_bucket" {
  description = "Name of the raw-data S3 bucket"
  value       = aws_s3_bucket.raw.bucket
}

output "s3_processed_bucket" {
  description = "Name of the processed-data S3 bucket"
  value       = aws_s3_bucket.processed.bucket
}

output "s3_artifacts_bucket" {
  description = "Name of the ETL artefacts S3 bucket"
  value       = aws_s3_bucket.artifacts.bucket
}

output "ecr_repository_url" {
  description = "ECR repository URL for Docker image pushes"
  value       = aws_ecr_repository.etl_agent.repository_url
}
