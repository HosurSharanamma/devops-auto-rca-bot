# The cluster itself, via the community module (same reasoning as the VPC
# module -- this is the standard way EKS gets provisioned in real
# environments, and it correctly wires up IRSA, the aws-auth config map,
# and security groups that would be easy to get wrong by hand).
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.project_name
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Lets you run kubectl from your own laptop against the cluster's public
  # API endpoint. Fine for a personal/portfolio project; a real production
  # cluster would restrict this to a VPN or bastion CIDR instead.
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = false

  # Gives the IAM identity that runs `terraform apply` (your terraform-cli
  # user) automatic cluster-admin via the EKS access entries API, so
  # `aws eks update-kubeconfig` + kubectl work immediately without manually
  # editing the aws-auth config map.
  enable_cluster_creator_admin_permissions = true

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]

      # Day 6: required once cluster_version is 1.33+. EKS no longer ships
      # Amazon Linux 2 node images for 1.33 and newer, and this module's
      # default is still AL2 -- without this line the node group fails to
      # create. AL2023 is the supported replacement.
      ami_type = "AL2023_x86_64_STANDARD"

      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      # On-demand, not spot -- spot is cheaper but can be reclaimed with 2
      # minutes' notice, which is an avoidable source of flaky demos while
      # you're actively working in a session. Worth revisiting as a
      # deliberate cost optimization later, and worth mentioning as one in
      # an interview.
      capacity_type = "ON_DEMAND"
    }
  }
}

# --- Day 4 addition: let the GitHub Actions CD workflow talk to this cluster ---
#
# `enable_cluster_creator_admin_permissions` above only grants admin to the
# IAM identity that ran `terraform apply` (your terraform-cli user). The
# GitHub Actions role is a completely different identity, so without this
# it could run `aws eks update-kubeconfig` fine (that's just an IAM-level
# API call) but every `kubectl` command would fail with a 403 -- Kubernetes
# RBAC inside EKS is governed by access entries, not by IAM policy alone.
resource "aws_eks_access_entry" "github_actions" {
  cluster_name  = module.eks.cluster_name
  principal_arn = data.terraform_remote_state.base.outputs.github_actions_role_arn
}

resource "aws_eks_access_policy_association" "github_actions_admin" {
  cluster_name  = module.eks.cluster_name
  principal_arn = data.terraform_remote_state.base.outputs.github_actions_role_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.github_actions]
}
