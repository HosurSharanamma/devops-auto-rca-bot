output "ecr_api_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_ui_repository_url" {
  value = aws_ecr_repository.ui.repository_url
}

output "github_actions_role_arn" {
  description = "Read by terraform/eks.tf (via terraform_remote_state) to grant this role EKS access -- also used directly in the GitHub Actions workflow YAML files."
  value       = aws_iam_role.github_actions.arn
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github_actions.arn
}
