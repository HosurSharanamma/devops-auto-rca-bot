"""
This is UI for Auto-RCA Bot, built with Streamlit. 
 users can paste Jenkins CI/CD failure logs and receive root cause analysis (RCA) results,
   including the identified root cause, recommended fix, confidence score, and similar past incidents retrieved from the RAG vector store.
"""
import json
import os

import requests
import streamlit as st

API_BASE_URL = os.environ.get("RCA_API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Auto-RCA Bot", page_icon="🛠️", layout="wide")

st.title("🛠️ Auto-RCA Bot — DevOps Incident Root Cause Assistant")
st.caption(
    "GenAI-powered root cause analysis for Jenkins CI/CD failures. "
    "RAG over historical incidents (ChromaDB) + local Mistral inference (LM Studio)."
)

with st.sidebar:
    st.header("Backend status")
    try:
        health = requests.get(f"{API_BASE_URL}/health", timeout=3).json()
        st.success("API reachable") if health.get("status") == "ok" else st.error("API unhealthy")
        st.write("Vector store ready:", "✅" if health.get("vector_store_ready") else "❌ (run scripts/ingest_logs.py)")
        st.write("LLM reachable:", "✅" if health.get("llm_reachable") else "❌ (start LM Studio local server)")
    except requests.exceptions.RequestException:
        st.error("API not reachable at " + API_BASE_URL)
        st.caption("Start it with: uvicorn api.main:app --reload --port 8000")

    st.divider()
    top_k = st.slider("Number of similar incidents to retrieve (top_k)", 1, 5, 3)

    st.divider()
    st.subheader("📊 Evaluation report")
    eval_path = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation_report.json")
    if os.path.exists(eval_path):
        with open(eval_path) as f:
            report = json.load(f)
        st.metric("Top-1 Accuracy", f"{report['top_1_accuracy']*100:.1f}%")
        st.metric("Top-3 Accuracy", f"{report['top_3_accuracy']*100:.1f}%")
        st.metric("Avg retrieval latency", f"{report['avg_latency_ms']:.1f} ms")
    else:
        st.caption("Run `python scripts/evaluate_retrieval.py` to generate this report.")

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
    if not log_text.strip():
        st.warning("Please paste a log or choose a sample before analyzing.")
    else:
        with st.spinner("Retrieving similar incidents and generating RCA..."):
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/rca",
                    json={"log_text": log_text, "top_k": top_k},
                    timeout=400,
                )
            except requests.exceptions.RequestException as exc:
                st.error(f"Could not reach the API: {exc}")
                resp = None

        if resp is not None:
            if resp.status_code != 200:
                st.error(f"Request failed: {resp.json().get('detail', resp.text)}")
            else:
                result = resp.json()

                if result.get("low_confidence_flag"):
                    st.warning("⚠️ Low confidence result — consider providing more log context or escalating to an engineer.")
                if result.get("used_fallback"):
                    st.info("ℹ️ Retrieval unavailable or no strong matches — this answer used LLM-only reasoning.")
                if result.get("error"):
                    st.error(f"Generation error (fallback response shown): {result['error']}")

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("### 🎯 Root Cause")
                    st.write(result["root_cause"])
                    st.markdown("### 🔧 Recommended Fix")
                    st.write(result["fix_recommendation"])
                with col2:
                    st.markdown("### Confidence")
                    st.progress(result["confidence"])
                    st.write(f"{result['confidence']*100:.0f}%")
                    st.markdown("### Latency")
                    st.write(f"{result['latency_ms']:.1f} ms")
                    if result.get("redactions_applied"):
                        st.markdown("### 🔒 PII Redacted")
                        st.write(", ".join(result["redactions_applied"]))

                st.markdown("### 📚 Similar Past Incidents Retrieved")
                if result["retrieved_incidents"]:
                    for inc in result["retrieved_incidents"]:
                        with st.expander(f"{inc['id']} · {inc['root_cause_category']} · similarity {inc['similarity_score']:.2f}"):
                            st.code(inc["log_text"])
                else:
                    st.caption("No similar incidents retrieved.")

st.divider()
st.caption("Auto-RCA Bot · RAG (ChromaDB + MiniLM, optionally fine-tuned) + Mistral (LM Studio, local, offline)")
