variable "aws_region" {
  description = "AWS region for everything in this project."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag resources this config creates."
  type        = string
  default     = "auto-rca-bot"
}

variable "github_repo" {
  description = "Your GitHub repo as owner/name -- scopes the OIDC trust policy so ONLY workflows running in this exact repo can assume the AWS role. Change this if you ever fork or rename the repo."
  type        = string
  default     = "HosurSharanamma/devops-auto-rca-bot"
}
