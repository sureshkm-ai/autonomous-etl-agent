variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used as prefix for all resources"
  type        = string
  default     = "etl-agent"
}

variable "environment" {
  description = "Environment: dev, staging, prod"
  type        = string
  default     = "prod"
}

variable "ec2_instance_type" {
  description = "EC2 instance type for the application server"
  type        = string
  default     = "t3.medium"
}

variable "ec2_ami_id" {
  description = "Amazon Linux 2023 AMI ID (update per region)"
  type        = string
  default     = "ami-0c02fb55956c7d316"  # us-east-1 Amazon Linux 2023
}

variable "ssh_public_key" {
  description = "SSH public key for EC2 access"
  type        = string
  sensitive   = true
}
