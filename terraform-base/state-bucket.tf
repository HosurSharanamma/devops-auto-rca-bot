# Day 5: S3 bucket that holds the Terraform state for BOTH stacks
# (terraform-base/ and terraform/). Lives in terraform-base/ because this
# stack is never destroyed -- the state bucket must outlive the cluster.
#
# Chicken-and-egg: a backend bucket can't store the state of the run that
# creates it. So the order is: apply this file with LOCAL state first, then
# add the backend "s3" block and run `terraform init -migrate-state`.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  # Bucket names are global across all AWS accounts; the account ID suffix
  # makes a collision practically impossible.
  bucket = "${var.project_name}-tfstate-${data.aws_caller_identity.current.account_id}"

  # Opposite of the ECR force_delete choice, on purpose: losing state means
  # Terraform forgets what it owns. A destroy must fail loudly here.
  lifecycle {
    prevent_destroy = true
  }
}

# Every state write keeps the old version -> you can roll back a bad state.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

# State files contain secrets in plain text (e.g. resource attributes),
# so encrypt at rest.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "tfstate_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}
