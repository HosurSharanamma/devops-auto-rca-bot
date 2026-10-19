# Reads outputs from terraform-base/ (the stack that is NOT destroyed
# between sessions) -- the GitHub Actions role ARN, so this cluster can
# grant it access. Day 5: reads from S3 instead of a relative file path, so
# this no longer depends on both folders sitting side by side on one laptop.
data "terraform_remote_state" "base" {
  backend = "s3"
  config = {
    bucket = "auto-rca-bot-tfstate-533267099143"
    key    = "base/terraform.tfstate"
    region = "eu-central-1"
  }
}
