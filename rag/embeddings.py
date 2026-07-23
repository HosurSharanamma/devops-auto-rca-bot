""" Wrapper around sentence-transformers to provide embeddings for RAG. 
Loads model once per process and not per request,avoids reloading a multi model on every API call
MiniLM ouputs 384-dimesnional vectors-speed and accuracy,256 token limit"""
from __future__ import annotations

import os
from functools import lru_cache

BASE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

FINE_TUNED_MODEL_DIR = os.path.join(
    os.path.dirname(__file__), "..", "finetune", "output", "minilm-jenkins-finetuned"
)


def resolve_model_path() -> str:
    if os.path.isdir(FINE_TUNED_MODEL_DIR) and os.listdir(FINE_TUNED_MODEL_DIR):
        return FINE_TUNED_MODEL_DIR
    return BASE_MODEL_NAME


@lru_cache(maxsize=1)
def get_embedding_model():
    """Lazily load and cache the sentence-transformers model.

    Import is deferred inside the function so that modules which only need
    type-checking / config (e.g. tests that mock this out) don't require
    sentence-transformers + torch to be installed just to import this file.
    """
    from sentence_transformers import SentenceTransformer

    model_path = resolve_model_path()
    return SentenceTransformer(model_path)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embeddings.tolist()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
