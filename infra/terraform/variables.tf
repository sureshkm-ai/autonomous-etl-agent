# =============================================================================
# variables.tf — legacy EC2 variables
#
# aws_region, project_name, and environment are now declared in
# ecs_variables.tf.  Only EC2-specific variables remain here so that
# ec2_bkp.tf.bak can be restored without merge conflicts if needed.
# =============================================================================

variable "ec2_instance_type" {
  description = "EC2 instance type for the application server (legacy)"
  type        = string
  default     = "t3.medium"
}

variable "ec2_ami_id" {
  description = "Amazon Linux 2023 AMI ID — us-east-1 (legacy)"
  type        = string
  default     = "ami-0c02fb55956c7d316"
}

variable "ssh_public_key" {
  description = "SSH public key for EC2 access (legacy)"
  type        = string
  sensitive   = true
  default     = ""
}
