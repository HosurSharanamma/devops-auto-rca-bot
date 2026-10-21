# Day 3 — Kubernetes manifests: deploy the app onto EKS

## What this adds

| File | Resource | Purpose |
|---|---|---|
| `00-namespace.yaml` | Namespace `auto-rca-bot` | Keeps this app's objects separate from cluster-system stuff. Free, good practice, worth mentioning in an interview. |
| `01-configmap.yaml` | ConfigMap | Non-secret env vars: Groq base URL, model name, internal API URL. |
| `02-api-deployment.yaml` | Deployment | Runs the FastAPI image from ECR. Readiness/liveness probes hit `/health` (built in Day 1). Resource requests/limits sized to actually fit a `t3.medium` node. |
| `03-api-service.yaml` | Service (ClusterIP) | Internal-only DNS name (`auto-rca-bot-api`) so the UI pod can reach the API pod. Never exposed outside the cluster. |
| `04-ui-deployment.yaml` | Deployment | Runs the Streamlit image from ECR. |
| `05-ui-service.yaml` | Service (NodePort) | You chose NodePort + port-forward over a LoadBalancer — no extra AWS cost. Access is via `kubectl port-forward`, not a public IP. |

The Groq API key is **not** in any of these files. It goes into a
Kubernetes Secret created directly on the command line, so it's never
written to disk in a form that could get committed to git or pasted
anywhere.

## Prerequisite — Day 2 cluster must be up

```bash
cd terraform
terraform apply
aws eks update-kubeconfig --region eu-central-1 --name auto-rca-bot
kubectl get nodes   # confirm 1 node, Ready
```

If you destroyed the cluster at the end of Day 2 (correct — that's the
rule), you need to `apply` it again before any of this works.

## 1. Create the namespace and config first

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
```

## 2. Create the secret — do this in your own terminal, never paste the key anywhere

If `LLM_API_KEY` is already set in your current PowerShell session (from
Day 1), reuse it directly:

```powershell
kubectl create secret generic auto-rca-bot-secrets `
  --from-literal=LLM_API_KEY=$env:LLM_API_KEY `
  -n auto-rca-bot
```

If it's not set in this session, set it first the same way you did on Day 1
(`$env:LLM_API_KEY="..."`), then run the command above. **Don't tell me when
it's set, don't paste the value anywhere in this chat — I only need to know
the command succeeded.**

Verify it exists (this shows the key name, not its value):
```bash
kubectl get secret auto-rca-bot-secrets -n auto-rca-bot
```

## 3. Deploy the app

```bash
kubectl apply -f k8s/02-api-deployment.yaml
kubectl apply -f k8s/03-api-service.yaml
kubectl apply -f k8s/04-ui-deployment.yaml
kubectl apply -f k8s/05-ui-service.yaml
```

(Or `kubectl apply -f k8s/` to apply everything in the folder at once —
Kubernetes doesn't care about ordering within one apply for these
resources, since nothing here has a strict dependency Kubernetes itself
enforces.)

## 4. Verify

```bash
kubectl get pods -n auto-rca-bot -w
```

Watch until both pods show `STATUS=Running` and `READY=1/1`. First pull from
ECR can take 30–90 seconds since the images aren't cached on the new node.

If a pod sits in `ImagePullBackOff`, your image tags/account ID in the
Deployment YAML don't match what's actually in ECR — check with
`aws ecr describe-images --repository-name auto-rca-bot-api --region eu-central-1`
and confirm the tag matches.

If a pod is `Running` but `READY=0/1`, the readiness probe is failing —
check why with:
```bash
kubectl logs -n auto-rca-bot deployment/auto-rca-bot-api
kubectl describe pod -n auto-rca-bot <pod-name>
```

## 5. Open the UI

```bash
kubectl port-forward -n auto-rca-bot svc/auto-rca-bot-ui 8501:8501
```

Leave that running, then open http://localhost:8501 in your browser — this
is now the Streamlit UI running on EKS, not on your laptop, tunneled to you
through kubectl. Paste a sample Jenkins log and confirm you get back a
grounded RCA, same as the Day 1 local verification but now served from the
cluster.

Optional, to prove the API pod directly (separate terminal, since
port-forward blocks the one it's running in):
```bash
kubectl port-forward -n auto-rca-bot svc/auto-rca-bot-api 8000:8000
curl http://localhost:8000/health
```

## 6. Capture your evidence before tearing down

- `kubectl get pods -n auto-rca-bot` output (both Running, both Ready)
- A screenshot of the UI working through the port-forward
- `kubectl get all -n auto-rca-bot` for a full picture of what's deployed

## 7. Tear down

Destroying the whole EKS cluster via Terraform removes everything in this
namespace automatically — you do NOT need a separate `kubectl delete` step
if you're ending the session:

```bash
cd terraform
terraform destroy
```

If you ever want to redeploy or tear down just the app while keeping the
cluster up (e.g. to test a new image without destroying infrastructure):
```bash
kubectl delete namespace auto-rca-bot
```
This deletes the namespace and everything in it (deployments, services,
configmap, secret) in one command, cluster stays up.

## Known trade-offs worth being upfront about in an interview

- **NodePort + port-forward, not a LoadBalancer or Ingress.** Deliberate
  cost call — a LoadBalancer Service provisions a real AWS Network Load
  Balancer (~$0.025/hr + data) that runs the whole time the Service exists,
  not just while you're using it. An Ingress would need the AWS Load
  Balancer Controller installed (its own Helm chart + IAM OIDC setup) —
  more moving parts than this project needs right now. Both are reasonable
  next steps for a "real" production-style setup, just not free ones.
- **Containers run as root.** The Dockerfiles from Day 1 don't set a
  non-root `USER`, so these pods run with the image's default (root). A
  production hardening pass would add a non-root user to both Dockerfiles
  and a `securityContext` here. Known gap, not done yet — good, honest
  thing to say if asked "what would you improve."
- **1 replica each, no HorizontalPodAutoscaler.** Fine for a demo/portfolio
  cluster with 1 node. A real deployment would run at least 2 replicas of
  the API for availability and use an HPA tied to CPU or request latency.
- **Image tag is `:latest`**, which is mutable — convenient here, but in a
  real pipeline you'd deploy by immutable tag (a git SHA or build number)
  so you always know exactly which code is running. This is exactly what
  Day 4's CI/CD pipeline will introduce.

---

# Day 6 — Observability: Prometheus metrics for the RCA bot

## What this adds

| File | What | Why |
|---|---|---|
| `api/metrics.py` | 2 metrics: `rca_request_duration_seconds` (histogram), `rca_requests_total` (counter) | Latency a user feels; error and low-confidence rates. LLM failures still return HTTP 200 with a fallback answer, so status codes alone hide them. |
| `api/main.py` | `GET /metrics` + one `record_rca()` call per request | What Prometheus scrapes. |
| `02-api-deployment.yaml` | `prometheus.io/*` pod annotations | Prometheus finds pods by annotation, not a fixed address. |
| `06-prometheus.yaml` | ServiceAccount, Role, RoleBinding, ConfigMap (config + rules), Deployment, Service | One small Prometheus (~192Mi) that fits the single t3.medium. Namespaced Role = least privilege. |
| `tests/test_metrics.py` | 4 tests | Same CI gate as Day 5. |
| CD workflow | Creates namespace + secret from GitHub secret `LLM_API_KEY`, applies all manifests with the chosen tag, smoke-tests `/health` and `/metrics` | Fresh cluster → running app in one click. `set image` alone could never deploy Prometheus or config changes. |
| CI workflow | `:latest` pushed only from `main` | Branch runs can't overwrite main's image. |

## Run it

```bash
# 1. Cluster up (now 1.35 -- see terraform/README.md Day 6 note)
cd terraform && terraform plan   # read it: expect cluster_version 1.35 and ami_type AL2023
terraform apply
aws eks update-kubeconfig --region eu-central-1 --name auto-rca-bot

# 2. One time only: GitHub repo -> Settings -> Secrets and variables -> Actions
#    -> Secrets tab -> New repository secret: LLM_API_KEY = your Groq key.
#    CD now creates the namespace + Kubernetes secret itself, so a fresh
#    cluster needs NO manual kubectl steps.

# 3. Push to main -> CI runs tests, builds, pushes images tagged with the SHA
# 4. Actions tab -> "CD - deploy to EKS" -> image_tag = that SHA
```

## Prove it works

```bash
kubectl port-forward svc/auto-rca-bot-ui 8501:8501 -n auto-rca-bot      # terminal 1
kubectl port-forward svc/prometheus 9090:9090 -n auto-rca-bot           # terminal 2
```

1. Run 5–10 RCAs from the UI (http://localhost:8501), including one empty input.
2. http://localhost:9090/targets — `auto-rca-bot-pods` must show **UP**.
3. Queries (Graph tab), after ~1 minute:
   - `rca_requests_total` — counts by outcome
   - `rca:latency_seconds:p95_5m` — p95 latency in seconds
   - `rca:low_confidence_ratio:5m` — share of answers flagged low confidence
4. Screenshot the targets page and the p95 graph for your README / interview.

Then: `terraform destroy`.
