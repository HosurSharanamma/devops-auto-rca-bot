# Reads outputs from terraform-base/ (the stack that is NOT destroyed
# between sessions) -- the GitHub Actions role ARN, so this cluster can
# grant it access. Day 5: reads from S3 instead of a relative file path, so
# this no longer depends on both folders sitting side by side on one laptop.
#
# The bucket name is built from the account ID of whoever runs Terraform,
# so no account ID is committed to the repo. Override with
# -var="tfstate_bucket=..." if the bucket ever lives somewhere else.
data "aws_caller_identity" "current" {}

locals {
  tfstate_bucket = coalesce(
    var.tfstate_bucket,
    "${var.project_name}-tfstate-${data.aws_caller_identity.current.account_id}",
  )
}

data "terraform_remote_state" "base" {
  backend = "s3"
  config = {
    bucket = local.tfstate_bucket
    key    = "base/terraform.tfstate"
    region = var.aws_region
  }
}
