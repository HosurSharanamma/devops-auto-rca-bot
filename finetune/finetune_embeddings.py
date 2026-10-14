"""
Usage:
    python finetune/finetune_embeddings.py
"""

import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_jenkins_logs.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "minilm-jenkins-finetuned")
BASE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

random.seed(42)


def build_training_pairs(records):
    """Group records by category and emit all same-category pairs as
    positive training examples for MultipleNegativesRankingLoss."""
    from collections import defaultdict

    by_category = defaultdict(list)
    for r in records:
        by_category[r["root_cause_category"]].append(r["log_text"])

    pairs = []
    for category, texts in by_category.items():
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                pairs.append((texts[i], texts[j]))
    random.shuffle(pairs)
    return pairs


def main(epochs: int = 4, batch_size: int = 8):
    from sentence_transformers import SentenceTransformer, InputExample, losses
    from torch.utils.data import DataLoader

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    pairs = build_training_pairs(records)
    print(f"Built {len(pairs)} positive training pairs from {len(records)} incidents.")

    train_examples = [InputExample(texts=[a, b]) for a, b in pairs]
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=batch_size)

    model = SentenceTransformer(BASE_MODEL_NAME)
    train_loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = max(1, int(len(train_dataloader) * epochs * 0.1))

    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=epochs,
        warmup_steps=warmup_steps,
        show_progress_bar=True,
        output_path=OUTPUT_DIR,
    )

    print(f"Fine-tuned model saved to {OUTPUT_DIR}")
    print("rag/embeddings.py will automatically pick this checkpoint up on next run.")


if __name__ == "__main__":
    main()
