terraform {
  required_version = ">= 1.10.0"

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

  # Day 5: state moved from local disk to S3. This state is NOT destroyed
  # between sessions -- it holds the cheap, long-lived things: ECR repos,
  # the GitHub OIDC role, and the state bucket itself.
  #
  # use_lockfile = S3-native state locking (Terraform >= 1.10), so two
  # applies (e.g. laptop + CI) can't corrupt state at the same time --
  # no DynamoDB table needed any more.
  # The bucket name is NOT hardcoded here: it ends in the AWS account ID.
  # Backend blocks cannot read variables, so it is passed at init time
  # (partial backend configuration). Works in bash and PowerShell:
  #   terraform init -backend-config="bucket=auto-rca-bot-tfstate-$(aws sts get-caller-identity --query Account --output text)"
  backend "s3" {
    key          = "base/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}
