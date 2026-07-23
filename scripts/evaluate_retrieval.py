"""
To check how good the reterival is, we run a batch of queries against the vector store
 and compute top-1 / top-3 accuracy.
Usage:
    python scripts/evaluate_retrieval.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.vector_store import query_similar  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_jenkins_logs.json")
EXTRA_K = 3  # fetch a few extra so we can drop the self-match and still have top_k


def evaluate(top_k: int = 3):
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    top1_hits = 0
    top3_hits = 0
    similarities = []
    latencies_ms = []

    for record in records:
        start = time.perf_counter()
        raw_results = query_similar(record["log_text"], top_k=top_k + EXTRA_K)
        latencies_ms.append((time.perf_counter() - start) * 1000)

        # Drop the self-match (same id), keep ordering, trim to top_k
        filtered = [r for r in raw_results if r["id"] != record["id"]][:top_k]

        if not filtered:
            continue

        true_category = record["root_cause_category"]
        if filtered[0]["root_cause_category"] == true_category:
            top1_hits += 1
            similarities.append(filtered[0]["similarity_score"])
        if any(r["root_cause_category"] == true_category for r in filtered):
            top3_hits += 1

    n = len(records)
    report = {
        "n_queries": n,
        "top_1_accuracy": round(top1_hits / n, 4) if n else 0.0,
        "top_3_accuracy": round(top3_hits / n, 4) if n else 0.0,
        "avg_top1_similarity": round(sum(similarities) / len(similarities), 4) if similarities else 0.0,
        "avg_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else 0.0,
    }
    return report


def main():
    report = evaluate(top_k=3)
    print(json.dumps(report, indent=2))

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report to {out_path}")


if __name__ == "__main__":
    main()
