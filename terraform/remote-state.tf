# Reads outputs from terraform-base/ (the state that is NOT destroyed
# between sessions) -- specifically the GitHub Actions role ARN, so this
# cluster can grant it access, and the ECR URLs, purely for convenience so
# `terraform output` still works the same way from this directory.
#
# This assumes terraform-base/ sits next to this terraform/ directory, i.e.
#   repo-root/terraform/        <- this directory
#   repo-root/terraform-base/   <- applied once, left standing
# Adjust the path below if your layout differs.
data "terraform_remote_state" "base" {
  backend = "local"
  config = {
    path = "${path.module}/../terraform-base/terraform.tfstate"
  }
}
