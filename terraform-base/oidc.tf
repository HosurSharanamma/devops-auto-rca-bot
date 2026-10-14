# Lets GitHub Actions workflows in YOUR repo assume an AWS role directly --
# no AWS access key/secret stored as a GitHub Secret, ever. GitHub issues a
# short-lived signed token to the workflow run; AWS trusts it because of the
# OIDC provider + the exact-repo condition on the role below. If this
# project's repeated credential-exposure history taught anything, it's that
# the safest long-lived AWS credential is the one that doesn't exist -- this
# removes that whole class of risk for CI/CD specifically.

# Fetches GitHub's current TLS certificate thumbprint dynamically rather
# than hardcoding it. GitHub has rotated this certificate before, which
# silently broke OIDC trust for anyone who hardcoded the old thumbprint --
# this way it's always correct at apply time.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

# Trust policy: ONLY workflow runs from this exact GitHub repo can assume
# this role. Scoped to the whole repo (any branch/PR/tag) rather than just
# `main` -- tight enough to block every other GitHub repo on earth, loose
# enough not to fight you while you're still iterating on workflow files.
data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_name}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

# ECR push permissions -- enough for the CI workflow to build and push
# images, nothing more.
data "aws_iam_policy_document" "ecr_push" {
  statement {
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
    ]
    resources = ["*"] # GetAuthorizationToken does not support resource-level restriction
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      aws_ecr_repository.api.arn,
      aws_ecr_repository.ui.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.ecr_push.json
}

# EKS permissions for the CD workflow -- enough to run `aws eks
# update-kubeconfig` and describe the cluster. The actual ability to run
# kubectl commands against the cluster comes from an EKS access entry
# granted to this role's ARN in the MAIN terraform/eks.tf (that's the file
# that owns the cluster) -- IAM alone doesn't grant Kubernetes RBAC access,
# EKS access entries do.
data "aws_iam_policy_document" "eks_describe" {
  statement {
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:aws:eks:${var.aws_region}:*:cluster/${var.project_name}"]
  }
}

resource "aws_iam_role_policy" "github_actions_eks_describe" {
  name   = "eks-describe"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.eks_describe.json
}
