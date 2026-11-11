terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Day 5: remote state in S3 (bucket created by terraform-base/).
  # Same bucket, different key, so the two stacks never overwrite each other.
  # The bucket name is NOT hardcoded here: it ends in the AWS account ID.
  # Backend blocks cannot read variables, so it is passed at init time
  # (partial backend configuration). Works in bash and PowerShell:
  #   terraform init -backend-config="bucket=auto-rca-bot-tfstate-$(aws sts get-caller-identity --query Account --output text)"
  backend "s3" {
    key          = "eks/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}
