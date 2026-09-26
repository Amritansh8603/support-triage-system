"""A dependency-free vector store.

Real systems would call an embedding API (OpenAI/Voyage/etc). Here we use a
deterministic hashed bag-of-words embedding so the whole project runs with
no network access and no API keys, while still exercising the same
interface (embed -> store -> cosine-similarity search) a real vector DB
integration would use.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def embed(text: str, dim: int = DIM) -> np.ndarray:
    """Deterministic hashed bag-of-words embedding, L2-normalized."""
    vec = np.zeros(dim, dtype=np.float64)
    for tok in _tokenize(text):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0  # cheap sign hashing
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


@dataclass
class Document:
    id: str
    text: str
    metadata: dict
    vector: np.ndarray


class VectorStore:
    """A minimal in-memory vector store with cosine-similarity search."""

    def __init__(self, dim: int = DIM):
        self.dim = dim
        self._docs: List[Document] = []

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        vec = embed(text, self.dim)
        self._docs.append(Document(id=doc_id, text=text, metadata=metadata or {}, vector=vec))

    def add_many(self, items: List[Tuple[str, str, dict]]) -> None:
        for doc_id, text, meta in items:
            self.add(doc_id, text, meta)

    def search(self, query: str, top_k: int = 3, category_filter: str | None = None):
        """Return up to top_k (Document, score) pairs, best first."""
        q_vec = embed(query, self.dim)
        scored = []
        for doc in self._docs:
            if category_filter and doc.metadata.get("category") != category_filter:
                continue
            score = cosine_similarity(q_vec, doc.vector)
            scored.append((doc, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._docs)


def build_default_kb() -> VectorStore:
    from .knowledge_base_data import ARTICLES

    store = VectorStore()
    for art in ARTICLES:
        text = f"{art['title']}. {art['content']}"
        store.add(art["id"], text, {"category": art["category"], "title": art["title"]})
    return store
