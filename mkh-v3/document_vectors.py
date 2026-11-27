"""Pinned multilingual sentence embeddings for public document sections and search queries."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

MODEL = "static-similarity-mrl-multilingual-v1@b68f412:128-int8-v1"
MODEL_DIR = Path(__file__).resolve().parent / "models" / "static-multilingual"


@lru_cache(maxsize=1)
def encoder():
    with np.load(MODEL_DIR / "weights.npz", allow_pickle=False) as data:
        return Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json")), data["weights"], data["scales"]


def encode(text):
    tokenizer, weights, scales = encoder()
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    if not ids:
        return np.zeros(128, dtype="float32")
    pooled = (weights[ids] * scales[ids, None]).sum(axis=0)
    return pooled / max(1e-12, float(np.linalg.norm(pooled)))
