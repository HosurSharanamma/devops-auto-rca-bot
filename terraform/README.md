# Day 2 — Terraform: networking, ECR, EKS

## What this builds

| File | Resource(s) | Purpose |
|---|---|---|
| `vpc.tf` | VPC, 2 public + 2 private subnets, 1 NAT gateway | Network EKS runs in. Nodes live in private subnets; the NAT gateway is how they reach the internet (pull images, call Groq) without a public IP each. |
| `ecr.tf` | 2 ECR repos (`auto-rca-bot-api`, `auto-rca-bot-ui`) + lifecycle policies | Where your Day 1 Docker images get pushed to, so EKS can pull them. |
| `eks.tf` | EKS cluster + 1 managed node group | The Kubernetes control plane + the actual EC2 worker node(s) pods run on. |
| `variables.tf` | — | All tunable defaults (region, sizes, counts) in one place. |
| `outputs.tf` | — | Prints the values you need for the next steps (ECR URLs, kubectl config command). |

Deliberate defaults (all changeable in `variables.tf`):
- 1 NAT gateway, not 1-per-AZ (cost, not redundancy)
- 1 worker node, `t3.medium`, autoscaling 1–2
- On-demand nodes, not spot (stability during active work)
- Local Terraform state (no S3 backend yet — that's a deliberate later step)

## Cost while this is running

Roughly **$0.20/hour** (on a Kubernetes version in **standard** support -- see Day 6 note below) all-in while up (EKS control plane ~$0.10/hr + 1
t3.medium ~$0.0416/hr + NAT gateway ~$0.045/hr + small data charges).
**Left running by accident for a month, this is closer to $140.** This is
exactly why the rule is: `apply` when you start working, `destroy` when
you stop. Nothing here runs on your laptop's resources — Terraform only
makes AWS API calls, so none of the earlier Docker/RAM problems apply.

## Prerequisites (from Day 1 — should already be true)

- `aws sts get-caller-identity` succeeds, using the `terraform-cli` IAM user
- `terraform -version`, `kubectl version --client`, `eksctl version` all work

## Workflow

```bash
cd terraform
terraform init      # downloads the aws/vpc/eks providers+modules
terraform plan       # shows what will be created — read this before applying
terraform apply       # takes ~12-15 minutes, mostly waiting on the EKS control plane
```

Type `yes` when prompted. Go make coffee — the EKS control plane alone
typically takes 10+ minutes to become ACTIVE.

When `apply` finishes, it prints outputs including a ready-to-run command:

```bash
aws eks update-kubeconfig --region eu-central-1 --name auto-rca-bot
kubectl get nodes
# should show 1 node, STATUS = Ready
```

That confirms the cluster is real and kubectl is talking to it. We are not
deploying the app onto it yet — manifests for that are Day 3. Today's goal
is: cluster exists, nodes are Ready, ECR repos exist.

## Push your Day 1 images to ECR (optional but recommended today)

Using the `ecr_api_repository_url` / `ecr_ui_repository_url` outputs:

```bash
aws ecr get-login-password --region eu-central-1 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.eu-central-1.amazonaws.com

docker tag auto-rca-bot-api:latest <ecr_api_repository_url>:latest
docker push <ecr_api_repository_url>:latest

docker tag auto-rca-bot-ui:latest <ecr_ui_repository_url>:latest
docker push <ecr_ui_repository_url>:latest
```

This proves the registry works and gets the images in place for the Day 3
Kubernetes manifests to reference.

## Before you stop working — every single time

```bash
terraform destroy
```

Type `yes` when prompted. Confirm in the AWS console (EC2 → Instances, EKS
→ Clusters) that nothing is left running. Capture your evidence first
(`kubectl get nodes` output, a screenshot, the ECR repos with images in
them) — this is your interview proof, since the live infrastructure won't
persist between sessions.

## Interview talking points this step gives you

- Why community modules (`terraform-aws-modules/vpc`, `.../eks`) over
  hand-rolled resources — faster, less error-prone, and what real teams use
- The public/private subnet split and why nodes sit in private subnets
- The NAT gateway cost/redundancy tradeoff (1 vs. per-AZ)
- `enable_cluster_creator_admin_permissions` — EKS access entries vs. the
  old aws-auth ConfigMap approach
- ECR lifecycle policies and why unbounded image retention is a quiet cost
  leak
- Why state is local for now and what moving to S3 + DynamoDB locking
  would change (team collaboration, state locking, avoiding "terraform
  apply from two laptops at once")

## Day 6 note — Kubernetes version and the hidden 6x control-plane cost

EKS charges **$0.10/hour** per cluster for a Kubernetes version in standard
support, and **$0.60/hour** once that version moves to extended support.
1.31 left standard support on 26 Nov 2025, so every session run on 1.31
paid the extended rate (~$0.70/hour all-in, not ~$0.20). Day 6 moves to
**1.35** (standard support until 27 Mar 2027). Because the cluster is
destroyed after every session, this is a fresh create at 1.35, not an
in-place upgrade. 1.33+ also needs `ami_type = "AL2023_x86_64_STANDARD"`
on the node group (no Amazon Linux 2 images exist for 1.33+).

Habit worth keeping: check the EKS version calendar before choosing a
version; the cost is applied automatically with no warning at apply time.
