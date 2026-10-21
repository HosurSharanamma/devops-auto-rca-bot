variable "aws_region" {
  description = "AWS region for everything in this project."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag every resource this config creates."
  type        = string
  default     = "auto-rca-bot"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "AZs to spread subnets across. Two is enough for EKS's requirement of 2+ AZs without paying for a third NAT path."
  type        = list(string)
  default     = ["eu-central-1a", "eu-central-1b"]
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane."
  type        = string
  default     = "1.35"
}

variable "node_instance_type" {
  description = "EC2 instance type for the EKS managed node group."
  type        = string
  default     = "t3.medium"
}

variable "node_min_size" {
  description = "Minimum worker nodes."
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum worker nodes (autoscaling ceiling)."
  type        = number
  default     = 2
}

variable "node_desired_size" {
  description = "Desired worker node count at apply time."
  type        = number
  default     = 1
}
