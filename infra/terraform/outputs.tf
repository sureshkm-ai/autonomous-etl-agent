output "app_public_ip" {
  description = "Public IP of the ETL Agent app server"
  value       = aws_eip.etl_agent.public_ip
}

output "app_public_dns" {
  description = "Public DNS of the ETL Agent app server"
  value       = aws_eip.etl_agent.public_dns
}

output "api_url" {
  description = "ETL Agent API base URL"
  value       = "http://${aws_eip.etl_agent.public_dns}:8000"
}

output "s3_raw_bucket" {
  value = aws_s3_bucket.raw.bucket
}

output "s3_processed_bucket" {
  value = aws_s3_bucket.processed.bucket
}

output "s3_artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "ecr_repository_url" {
  description = "ECR repository URL for Docker image pushes"
  value       = aws_ecr_repository.etl_agent.repository_url
}
