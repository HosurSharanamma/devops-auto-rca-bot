"""
finetune/finetune_embeddings.py

Domain fine-tuning of the sentence-transformers embedding model
(all-MiniLM-L6-v2) on the Jenkins failure-log domain.

Approach:
  - Build positive pairs from historical incidents that share the same
    root_cause_category (e.g. two different OOM-kill logs are a positive
    pair; an OOM-kill log and a dependency-resolution log are not).
  - Train with MultipleNegativesRankingLoss (in-batch negatives), which is
    the standard contrastive approach for retrieval-oriented fine-tuning:
    for each positive pair, every other example in the batch is treated as
    an implicit negative.
  - Save the resulting checkpoint to finetune/output/minilm-jenkins-finetuned/.
    rag/embeddings.py automatically detects and prefers this checkpoint if
    present (see resolve_model_path()); no other code changes are needed.

Usage:
    python finetune/finetune_embeddings.py

Requires: sentence-transformers, torch (already in requirements.txt).
This is optional -- the base MiniLM model is still fully functional
without this step.
"""

from __future__ import annotations

import itertools
import json
import os
import random

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_jenkins_logs.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "minilm-jenkins-finetuned")
BASE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

RANDOM_SEED = 42
NUM_EPOCHS = 4
BATCH_SIZE = 16
WARMUP_RATIO = 0.1


def load_records() -> list[dict]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_positive_pairs(records: list[dict]) -> list[tuple[str, str]]:
    """Pair up logs that share a root_cause_category.

    Every unordered pair within a category becomes one training example.
    Categories with only one example contribute no pairs (nothing to
    contrast them with) and are skipped.
    """
    by_category: dict[str, list[str]] = {}
    for r in records:
        by_category.setdefault(r["root_cause_category"], []).append(r["log_text"])

    pairs: list[tuple[str, str]] = []
    for category, texts in by_category.items():
        if len(texts) < 2:
            continue
        pairs.extend(itertools.combinations(texts, 2))

    random.Random(RANDOM_SEED).shuffle(pairs)
    return pairs


def main() -> None:
    # Imports deferred so this module can be inspected/imported without
    # requiring torch + sentence-transformers to be installed.
    from sentence_transformers import (
        InputExample,
        SentenceTransformer,
        losses,
    )
    from torch.utils.data import DataLoader

    random.seed(RANDOM_SEED)

    records = load_records()
    pairs = build_positive_pairs(records)
    if not pairs:
        raise SystemExit(
            "No same-category pairs found -- need at least two examples per "
            "root_cause_category in data/synthetic_jenkins_logs.json to fine-tune."
        )

    print(f"Loaded {len(records)} incidents -> {len(pairs)} positive training pairs.")

    train_examples = [InputExample(texts=[a, b]) for a, b in pairs]
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=BATCH_SIZE)

    print(f"Loading base model: {BASE_MODEL_NAME}")
    model = SentenceTransformer(BASE_MODEL_NAME)

    # MultipleNegativesRankingLoss: for each (a, b) positive pair, every
    # other b' in the batch acts as an in-batch negative for a. This is the
    # standard loss for fine-tuning retrieval/embedding models on pairs
    # without needing explicit hard negatives.
    train_loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = int(len(train_dataloader) * NUM_EPOCHS * WARMUP_RATIO)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Fine-tuning for {NUM_EPOCHS} epochs (batch_size={BATCH_SIZE}, warmup_steps={warmup_steps})...")

    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=NUM_EPOCHS,
        warmup_steps=warmup_steps,
        show_progress_bar=True,
        output_path=OUTPUT_DIR,
    )

    print(f"\nSaved fine-tuned checkpoint to: {OUTPUT_DIR}")
    print(
        "rag/embeddings.py will automatically use this checkpoint on the next "
        "run of scripts/ingest_logs.py or the API -- delete the folder to "
        "fall back to the base model."
    )


if __name__ == "__main__":
    main()
