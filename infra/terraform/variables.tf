<<<<<<< HEAD
# =============================================================================
# variables.tf — legacy EC2 variables
#
# aws_region, project_name, and environment are now declared in
# ecs_variables.tf.  Only EC2-specific variables remain here so that
# ec2_bkp.tf.bak can be restored without merge conflicts if needed.
# =============================================================================

variable "ec2_instance_type" {
  description = "EC2 instance type for the application server (legacy)"
=======
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
>>>>>>> main
  type        = string
  default     = "t3.medium"
}

variable "ec2_ami_id" {
<<<<<<< HEAD
  description = "Amazon Linux 2023 AMI ID — us-east-1 (legacy)"
  type        = string
  default     = "ami-0c02fb55956c7d316"
}

variable "ssh_public_key" {
  description = "SSH public key for EC2 access (legacy)"
  type        = string
  sensitive   = true
  default     = ""
=======
  description = "Amazon Linux 2023 AMI ID (update per region)"
  type        = string
  default     = "ami-0c02fb55956c7d316"  # us-east-1 Amazon Linux 2023
}

variable "ssh_public_key" {
  description = "SSH public key for EC2 access"
  type        = string
  sensitive   = true
>>>>>>> main
}
