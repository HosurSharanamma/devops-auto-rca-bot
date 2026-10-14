# ECR outputs now come from terraform-base/ (that's where the repos live as
# of Day 4) -- passed through here so `terraform output` from this
# directory still works the same way it always has.
output "ecr_api_repository_url" {
  description = "Push the API image here (docker tag + docker push)."
  value       = data.terraform_remote_state.base.outputs.ecr_api_repository_url
}

output "ecr_ui_repository_url" {
  description = "Push the UI image here (docker tag + docker push)."
  value       = data.terraform_remote_state.base.outputs.ecr_ui_repository_url
}

output "cluster_name" {
  description = "Pass this to: aws eks update-kubeconfig --region <region> --name <this>"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "configure_kubectl" {
  description = "Exact command to wire up kubectl against the new cluster."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "vpc_id" {
  description = "VPC ID, useful for sanity-checking in the AWS console."
  value       = module.vpc.vpc_id
}
