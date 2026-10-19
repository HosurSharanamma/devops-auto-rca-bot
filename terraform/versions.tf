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
  backend "s3" {
    bucket       = "auto-rca-bot-tfstate-533267099143"
    key          = "eks/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}
