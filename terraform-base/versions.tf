terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Local state, same as the main terraform/ directory. This state is NOT
  # destroyed between sessions (see README) -- it holds the things that cost
  # nothing to leave running: ECR repos and an IAM role.
}
