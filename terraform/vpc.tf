# Networking for the EKS cluster: public subnets for the NAT gateway/load
# balancers, private subnets for the worker nodes. Using the official
# community module instead of hand-writing ~10 resources -- this is also
# what most real teams do, so it's a fair thing to have used in an
# interview answer.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.8"

  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  private_subnets = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  # Single NAT gateway (not one per AZ) -- deliberate cost tradeoff. One NAT
  # gateway is ~$0.045/hr + data processing; one per AZ would double that for
  # redundancy this project doesn't need. Worth saying out loud in an
  # interview: this is a cost/availability tradeoff, made on purpose.
  enable_nat_gateway = true
  single_nat_gateway = true

  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags EKS needs to auto-discover subnets for load balancers and to know
  # which subnets are public vs. private for ELB placement.
  public_subnet_tags = {
    "kubernetes.io/cluster/${var.project_name}" = "shared"
    "kubernetes.io/role/elb"                    = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/cluster/${var.project_name}" = "shared"
    "kubernetes.io/role/internal-elb"           = "1"
  }
}
