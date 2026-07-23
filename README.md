# Auto-RCA Bot — DevOps Incident Root Cause Assistant

A GenAI-powered Root Cause Analysis (RCA) assistant for Jenkins CI/CD failures.
It retrieves similar historical incidents (RAG over ChromaDB) and uses a local
LLM (Mistral, served by LM Studio) to produce a grounded root cause and fix
recommendation — fully offline, with PII masking and error-handling guardrails
built in.

See `RUBRIC_MAPPING.md` for exactly how each part of this repo maps to the
grading rubric, and `DEMO_SCRIPT.md` for a step-by-step walkthrough to present
to the evaluator.

## Try it live
There's also a public, no-setup-required version of this tool — see
[`live/README.md`](live/README.md) for the deployment guide, or just open
the deployed link if one is already live for this repo. It swaps the local
LM Studio + sentence-transformers stack for a free hosted LLM (Groq) and a
lighter embedding approach, so it can run entirely on a free hosting tier.

## Architecture

```
Jenkins failure log
      |
      v
[utils/log_cleaning.py]   -> strip ANSI/timestamps, validate (empty/unsupported input)
      |
      v
[utils/pii_masking.py]    -> redact emails, IPs, tokens, keys, secrets
      |
      v
[rag/retrieval.py] -----> [rag/vector_store.py] (ChromaDB) -> top-k similar past incidents
      |                          ^
      |                          |
      |                   [rag/embeddings.py] (MiniLM, optionally fine-tuned)
      v
[rag/rca_generation.py]   -> prompt construction (grounded on retrieved incidents)
      |                       -> call local LLM (Mistral via LM Studio, OpenAI-compatible API)
      |                       -> retry w/ backoff on API failure, JSON output validation,
      |                          low-confidence flagging, fallback to LLM-only reasoning
      v
  RCA + fix recommendation
      |
      +--> [api/main.py] FastAPI (/health, /rca)  <-- used by ui/streamlit_app.py
      +--> [jenkins/Jenkinsfile.example]  post{failure{...}} -> Slack alert
```

### Repo layout

```
auto-rca-bot/
├── data/                      synthetic dataset + generated ChromaDB store + eval report
├── utils/                     log_cleaning.py, pii_masking.py
├── rag/                       embeddings.py, vector_store.py, retrieval.py, rca_generation.py
├── models/                    schemas.py (Pydantic API contracts)
├── scripts/                   generate_synthetic_data.py, ingest_logs.py, evaluate_retrieval.py
├── finetune/                  finetune_embeddings.py (domain fine-tuning of the embedding model)
├── api/                       main.py (FastAPI backend)
├── ui/                        streamlit_app.py (demo UI)
├── jenkins/                   Jenkinsfile.example (real pipeline integration)
├── tests/                     test_guardrails.py (offline unit tests)
├── RUBRIC_MAPPING.md
├── DEMO_SCRIPT.md
└── requirements.txt
```

## Setup

### 1. Prerequisites
- Python 3.10+
- [LM Studio](https://lmstudio.ai/) installed locally (for offline Mistral inference)
- ~4 GB free disk space for the Mistral-7B-Instruct GGUF model + embedding model

### 2. Clone / unzip and create a virtual environment
```bash
cd auto-rca-bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start the local LLM (LM Studio)
1. Open LM Studio → search and download **Mistral-7B-Instruct** (any quantized GGUF build, e.g. Q4_K_M).
2. Go to the **Local Server** tab → select the Mistral model → click **Start Server**.
3. Confirm it's running at `http://localhost:1234/v1` (default). If you use a
   different port/model name, set:
   ```bash
   export LM_STUDIO_BASE_URL=http://localhost:1234/v1
   export LM_STUDIO_MODEL=mistral-7b-instruct
   ```

### 4. Generate the synthetic dataset (already included, but reproducible)
```bash
python scripts/generate_synthetic_data.py
```
Writes `data/synthetic_jenkins_logs.json` — 40 labelled Jenkins failure logs
across 10 root-cause categories (OOM kills, flaky tests, dependency
resolution, config parse errors, network timeouts, credential/auth
failures, disk space, real regressions, infra provisioning, linting).

### 5. (Optional) Fine-tune the embedding model on the Jenkins domain
```bash
python finetune/finetune_embeddings.py
```
This fine-tunes `all-MiniLM-L6-v2` using contrastive learning (`MultipleNegativesRankingLoss`)
on same-category log pairs, and saves the checkpoint to
`finetune/output/minilm-jenkins-finetuned/`. `rag/embeddings.py` automatically
detects and uses this checkpoint if present — no other code changes needed.
Skip this step to use the base model instead (still fully functional).

### 6. Ingest the dataset into ChromaDB
```bash
python scripts/ingest_logs.py
```

### 7. Run retrieval evaluation
```bash
python scripts/evaluate_retrieval.py
```
Prints and saves `data/evaluation_report.json` with Top-1/Top-3 accuracy,
average similarity, and average latency. The Streamlit sidebar displays this
report automatically.

### 8. Start the backend API
```bash
uvicorn api.main:app --reload --port 8000
```
Check it's healthy: `curl http://localhost:8000/health`

### 9. Start the demo UI
```bash
streamlit run ui/streamlit_app.py
```
Opens at `http://localhost:8501`.

### 10. Run the offline guardrail tests (no model/LLM required)
```bash
python -m pytest tests/test_guardrails.py -v
```

## Demo flow (for the evaluator)
See `DEMO_SCRIPT.md` for the full walkthrough. Short version:
1. Show `/health` — vector store + LLM both green.
2. Paste a sample OOM-kill log in the UI → show retrieved similar incidents,
   grounded root cause + fix, confidence score, latency.
3. Paste a log containing a fake email/token → show the PII redaction badge.
4. Paste gibberish/empty input → show the structured validation error.
5. Show `data/evaluation_report.json` / sidebar metrics → Top-1/Top-3 accuracy.
6. Show `finetune/finetune_embeddings.py` and explain the fine-tuning approach.
7. Show `jenkins/Jenkinsfile.example` → explain real pipeline integration to Slack.

## Notes on offline/enterprise readiness
- No log data or PII ever leaves the local machine: embeddings, vector
  search, and LLM inference are all local (ChromaDB persistent store +
  LM Studio local server).
- PII masking runs before anything is embedded or sent to the LLM.
- All external-service calls (LLM only) use retry-with-backoff and timeouts;
  every failure mode produces a structured response, never a raw exception.
