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
  # Backend blocks cannot use variables, so the bucket name is hardcoded.
  # use_lockfile = S3-native state locking (Terraform >= 1.10), so two
  # applies (e.g. laptop + CI) can't corrupt state at the same time --
  # no DynamoDB table needed any more.
  backend "s3" {
   bucket       = "auto-rca-bot-tfstate-533267099143"
    key          = "base/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}
