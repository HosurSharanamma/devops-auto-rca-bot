# Rubric Mapping

How each capstone requirement maps to a concrete artifact in this repo.

| Requirement | Where it lives | Notes |
|---|---|---|
| **Problem framing / use case** | `README.md` (Architecture section) | Jenkins CI/CD failure triage; grounded RCA + fix recommendation. |
| **Data** | `data/synthetic_jenkins_logs.json`, `scripts/generate_synthetic_data.py` | 40 labelled logs across 10 root-cause categories. Regenerable, reproducible via fixed seed. |
| **Retrieval (RAG)** | `rag/vector_store.py`, `rag/retrieval.py`, `rag/embeddings.py` | ChromaDB persistent store, cosine similarity, MiniLM embeddings (base or fine-tuned). |
| **Embedding fine-tuning** | `finetune/finetune_embeddings.py` | Contrastive fine-tuning (`MultipleNegativesRankingLoss`) on same-category log pairs. Optional; auto-detected by `rag/embeddings.py` if present. |
| **Generation (LLM)** | `rag/rca_generation.py` | Local Mistral-7B via LM Studio (OpenAI-compatible `/v1/chat/completions`), grounded prompt built from retrieved incidents. |
| **Guardrails — input validation** | `utils/log_cleaning.py` | Empty-input rejection, ANSI/timestamp stripping, non-printable/binary input rejection, length capping. |
| **Guardrails — PII/secret redaction** | `utils/pii_masking.py` | Emails, IPs, AWS keys, bearer tokens, JWTs, private-key blocks, generic secret key=value pairs, phone numbers — all masked before embedding or LLM calls. |
| **Guardrails — error handling** | `rag/rca_generation.py`, `api/main.py` | Retry-with-backoff on LLM call failure, structured JSON-output validation, low-confidence flagging, fallback-to-LLM-only-reasoning on retrieval failure. No raw exception ever reaches the caller. |
| **API contract** | `models/schemas.py`, `api/main.py` | Pydantic request/response schemas; `GET /health`, `POST /rca`. |
| **Evaluation** | `scripts/evaluate_retrieval.py`, `data/evaluation_report.json` | Top-1 / Top-3 retrieval accuracy, average similarity, average latency, computed against the labelled dataset (self-match excluded). |
| **Testing** | `tests/test_guardrails.py` | Offline unit tests for input validation and PII masking — no model, vector store, or LLM required; safe for CI. |
| **User-facing demo** | `ui/streamlit_app.py` | Paste-a-log UI, sidebar health/eval metrics, sample logs, PII-redaction badge, confidence/latency display, retrieved-incident inspection. |
| **Real-world integration path** | `jenkins/Jenkinsfile.example` | `post { failure { ... } }` block calling the `/rca` API and posting the result to Slack — shows this isn't just a manual demo tool. |
| **Offline / enterprise readiness** | `README.md` (Notes section) | All inference (embeddings + LLM) is local; PII masking runs before anything leaves the process; no external network calls in the RAG/generation path. |

## Known limitations (disclosed, not hidden)
- `retrieval_failed` in `rag/retrieval.py` is only set `True` on an actual
  exception from the vector store (e.g. ChromaDB unavailable) — it does
  **not** currently trigger on a low-similarity-but-technically-successful
  retrieval. A future improvement would add a similarity-score threshold so
  "no *good* matches found" also routes to LLM-only reasoning with a
  `used_fallback` flag, not just "no matches found at all."
- The dataset (40 synthetic incidents / 10 categories) is intentionally
  small for a capstone demo. Retrieval accuracy figures in
  `data/evaluation_report.json` should be read as a demonstration of the
  evaluation *methodology*, not as production-scale accuracy.
