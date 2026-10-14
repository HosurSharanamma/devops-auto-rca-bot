terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Local state for now, deliberately. S3 remote state is a planned later
  # step (not Day 2) -- introducing it is itself worth doing as a separate,
  # understood step rather than bundling it in here.
  #
  # backend "s3" {}
}
