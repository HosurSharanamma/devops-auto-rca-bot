provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "auto-rca-bot"
      ManagedBy   = "terraform"
      Environment = "dev"
      TFState     = "base"
    }
  }
}
