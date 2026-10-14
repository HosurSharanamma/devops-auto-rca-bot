# Moved here from the main terraform/ecr.tf on Day 4. Why: the main
# terraform/ directory gets destroyed and re-applied every session (cost
# discipline), which used to wipe these repos every time too -- meaning
# every session had to rebuild and re-push both Docker images before
# Kubernetes could pull them, and CI/CD could never push an image outside
# of an active work session. ECR storage costs pennies a month (unlike the
# EKS cluster's per-hour charges), so there's no reason to tear it down.
# This state stays applied; only terraform/ (VPC, EKS) gets destroyed.
resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "ui" {
  name                 = "${var.project_name}-ui"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

locals {
  ecr_lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep last 15 tagged images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 15
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = local.ecr_lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "ui" {
  repository = aws_ecr_repository.ui.name
  policy     = local.ecr_lifecycle_policy
}
