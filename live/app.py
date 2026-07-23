"""
live/app.py

Public, single-service version of the Auto-RCA Bot: paste a Jenkins failure
log, get a grounded root-cause + fix recommendation, in your browser --
no local LLM or vector DB setup required.

Differences from the offline capstone version (see ../README.md):
  - LLM: Groq's free hosted API instead of local LM Studio/Mistral.
  - Embeddings: ChromaDB's built-in ONNX MiniLM (no torch) instead of
    sentence-transformers, to keep the footprint small on free hosting.
  - Vector store: rebuilt in-memory from the bundled dataset on startup,
    instead of a persistent on-disk store.
  - A simple per-session rate limit, since this is a public tool sharing
    one developer's free API key.

Run locally:
    export GROQ_API_KEY=...   # free key: https://console.groq.com/keys
    streamlit run live/app.py

Deploy: see live/README.md.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.log_cleaning import LogValidationError, validate_log_input  # noqa: E402

from live.rca_generation import generate_rca, is_llm_configured  # noqa: E402
from live.retrieval import retrieve_similar_incidents  # noqa: E402
from live.vector_store import build_collection  # noqa: E402

MAX_REQUESTS_PER_SESSION = 15
COOLDOWN_SECONDS = 10

st.set_page_config(page_title="Auto-RCA Bot", page_icon="🛠️", layout="wide")


# Load Streamlit secrets (when deployed) into env vars so the rag/ modules
# (which read os.environ, matching the offline version's convention) work
# unchanged whether run locally or on Streamlit Community Cloud.
for key in ("GROQ_API_KEY", "GROQ_MODEL"):
    if key in st.secrets and not os.environ.get(key):
        os.environ[key] = st.secrets[key]


@st.cache_resource(show_spinner="Loading knowledge base of past incidents...")
def get_collection():
    return build_collection()


st.title("🛠️ Auto-RCA Bot — DevOps Incident Root Cause Assistant")
st.caption(
    "Paste a Jenkins CI/CD failure log and get a grounded root cause + fix, "
    "retrieved from a knowledge base of past incidents and reasoned over by an LLM. "
    "Nothing you paste is stored."
)

if not is_llm_configured():
    st.warning(
        "⚠️ This deployment doesn't have an LLM API key configured yet. "
        "Retrieval will still work, but generation will show a placeholder. "
        "(Site operator: see live/README.md.)"
    )

with st.sidebar:
    st.header("About")
    st.write(
        "Open-source tool for any DevOps engineer triaging Jenkins failures. "
        "Built on a RAG pipeline (ChromaDB) + Groq-hosted LLM."
    )
    top_k = st.slider("Number of similar incidents to retrieve", 1, 5, 3)
    st.divider()
    st.caption(
        f"Rate limit: {MAX_REQUESTS_PER_SESSION} analyses per browser session, "
        f"{COOLDOWN_SECONDS}s between requests -- keeps this free for everyone."
    )
    st.caption("[Source code on GitHub](https://github.com/HosurSharanamma/devops-auto-rca-bot)")

st.subheader("Paste a Jenkins failure log")

sample_logs = {
    "-- choose a sample --": "",
    "OOM kill": "Build step 'mvn test' failed. Container exited with code 137. dmesg: Out of memory: Killed process (java).",
    "Config parse error": "Pipeline failed at 'Load Config' stage: yaml.scanner.ScannerError: mapping values are not allowed here, line 12, column 12.",
    "Dependency resolution": "npm install failed: 404 Not Found - GET https://registry.npmjs.org/left-pad/-/left-pad-1.3.1.tgz",
}
choice = st.selectbox("Or load a sample log", list(sample_logs.keys()))

log_text = st.text_area(
    "Log text",
    value=sample_logs[choice],
    height=200,
    placeholder="Paste the Jenkins console output / failure snippet here...",
)

analyze_clicked = st.button("🔍 Analyze Root Cause", type="primary")

if analyze_clicked:
    request_count = st.session_state.get("request_count", 0)
    last_request_time = st.session_state.get("last_request_time", 0.0)
    now = time.time()

    if request_count >= MAX_REQUESTS_PER_SESSION:
        st.error(
            f"You've reached the {MAX_REQUESTS_PER_SESSION}-analysis limit for this session. "
            "Refresh the page to reset, or run this yourself from the source repo."
        )
    elif now - last_request_time < COOLDOWN_SECONDS:
        st.warning(f"Please wait a few seconds between requests (shared free tier).")
    elif not log_text.strip():
        st.warning("Please paste a log or choose a sample before analyzing.")
    else:
        try:
            cleaned = validate_log_input(log_text)
        except LogValidationError as exc:
            st.error(str(exc))
            cleaned = None

        if cleaned:
            st.session_state["request_count"] = request_count + 1
            st.session_state["last_request_time"] = now

            with st.spinner("Retrieving similar incidents and generating RCA..."):
                collection = get_collection()
                retrieval_outcome = retrieve_similar_incidents(collection, cleaned, top_k=top_k)
                result = generate_rca(
                    cleaned_log_text=cleaned,
                    incidents=retrieval_outcome.incidents,
                    retrieval_failed=retrieval_outcome.retrieval_failed,
                )

            if result.low_confidence_flag:
                st.warning("⚠️ Low confidence result — consider providing more log context.")
            if result.used_fallback and not result.error:
                st.info("ℹ️ Retrieval unavailable — this answer used LLM-only reasoning.")
            if result.error:
                st.error(f"Generation note: {result.error}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 🎯 Root Cause")
                st.write(result.root_cause)
                st.markdown("### 🔧 Recommended Fix")
                st.write(result.fix_recommendation)
            with col2:
                st.markdown("### Confidence")
                st.progress(result.confidence)
                st.write(f"{result.confidence*100:.0f}%")
                st.markdown("### Latency")
                st.write(f"{result.latency_ms:.1f} ms")
                if retrieval_outcome.redactions_applied:
                    st.markdown("### 🔒 PII Redacted")
                    st.write(", ".join(retrieval_outcome.redactions_applied))

            st.markdown("### 📚 Similar Past Incidents Retrieved")
            if retrieval_outcome.incidents:
                for inc in retrieval_outcome.incidents:
                    with st.expander(f"{inc['id']} · {inc['root_cause_category']} · similarity {inc['similarity_score']:.2f}"):
                        st.code(inc["log_text"])
            else:
                st.caption("No similar incidents retrieved.")

st.divider()
st.caption("Auto-RCA Bot · RAG (ChromaDB) + Llama (Groq, hosted, free tier) · Your logs are never stored.")
