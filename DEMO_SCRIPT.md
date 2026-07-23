# Demo Script

A step-by-step walkthrough for presenting the Auto-RCA Bot to an evaluator.
Total time: ~6-8 minutes. Do the setup (steps 0) *before* the room fills up.

## 0. Before you start (setup, not part of the timed demo)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start LM Studio's local server (Mistral-7B-Instruct loaded, port 1234) first.

python scripts/generate_synthetic_data.py     # if data/ is empty
python scripts/ingest_logs.py                 # populate ChromaDB
python scripts/evaluate_retrieval.py          # generate the eval report

uvicorn api.main:app --reload --port 8000     # terminal 1
streamlit run ui/streamlit_app.py             # terminal 2
```

## 1. Health check (30 sec)
Open the Streamlit sidebar. Point out:
- **API reachable** ✅
- **Vector store ready** ✅ (backed by ChromaDB, persisted to `data/chroma_store/`)
- **LLM reachable** ✅ (LM Studio local server, fully offline)

If any of these is ❌, say so honestly and explain the fallback behavior
(next section) rather than trying to hide it.

## 2. Happy path — grounded RCA (2 min)
Paste the **OOM kill** sample log (or your own). Click **Analyze Root Cause**.
Walk through the response:
- **Root Cause** and **Recommended Fix** — grounded in retrieved incidents,
  not just the LLM's prior knowledge.
- **Confidence** score and **Latency**.
- Expand **Similar Past Incidents Retrieved** — show the similarity scores
  and that the retrieved incidents are genuinely relevant to the category
  (e.g. other OOM/memory-limit failures).

## 3. PII redaction (1 min)
Paste a log containing a fake email and token, e.g.:
```
Build failed. Contact admin@acme.com token=abcd1234efgh5678 from ip 10.0.0.42
```
Point out the **🔒 PII Redacted** badge listing which rules fired
(`EMAIL`, `GENERIC_SECRET_KV`, `IPV4`). Emphasize: masking happens **before**
the text is embedded or sent to the LLM — nothing sensitive leaves the
process in either direction.

## 4. Input validation guardrail (1 min)
Submit an empty log, or a few random symbols. Show the structured
`400 invalid_input` response in the UI (`st.warning` / `st.error`), not a
raw stack trace or a hung request.

## 5. Failure-mode guardrail (1 min, optional but strong signal)
Stop the LM Studio server (or kill the API), then submit a log. Show that
the response is still a well-formed JSON object — not a crash — with
`used_fallback: true`, `low_confidence_flag: true`, and a human-readable
`error` field. This is the retry-with-backoff + structured-error-handling
path in `rag/rca_generation.py` doing its job. Restart LM Studio afterward.

## 6. Evaluation metrics (1 min)
Point to the sidebar's **📊 Evaluation report**: Top-1 / Top-3 retrieval
accuracy and average latency, computed by `scripts/evaluate_retrieval.py`
against the labelled dataset. Mention `RUBRIC_MAPPING.md` if the evaluator
wants the full breakdown of where each requirement is implemented.

## 7. Fine-tuning story (30 sec)
Show `finetune/finetune_embeddings.py`. Explain: contrastive fine-tuning
(`MultipleNegativesRankingLoss`) on same-category log pairs, applied to the
base MiniLM embedding model. `rag/embeddings.py` auto-detects the fine-tuned
checkpoint if present — no code changes needed to switch between base and
fine-tuned. This is optional and skippable; the system works with the base
model too.

## 8. Real pipeline integration (30 sec)
Show `jenkins/Jenkinsfile.example` — a `post { failure { ... } } ` block that
calls the `/rca` API automatically on build failure and posts the result to
Slack. This is the intended production integration path: the Streamlit UI is
for demo/manual triage, but the API is designed to be called by Jenkins
itself.

## Closing line
"Everything here — embeddings, vector search, and LLM inference — runs
locally. No log data or PII ever leaves the machine."
