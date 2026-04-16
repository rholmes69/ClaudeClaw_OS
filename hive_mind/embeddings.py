"""Hive Mind — Embeddings

Gemini embedding wrapper for 768-dimensional semantic vectors.
Used by Memory v2 for semantic search and duplicate detection.
"""

import os
import struct
from typing import Optional

import numpy as np
from google import genai

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        _client = genai.Client(api_key=api_key)
    return _client


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 768-dimensional embedding vector for the given text.
    Uses gemini-embedding-001 via the Google GenAI SDK.
    """
    client = _get_client()
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
    )
    return list(result.embeddings[0].values)


def encode_embedding(vec: list[float]) -> str:
    """Encode a float32 vector to a hex string for SQLite storage."""
    packed = struct.pack(f"{len(vec)}f", *vec)
    return packed.hex()


def decode_embedding(hex_str: str) -> list[float]:
    """Decode a hex string back to a float32 vector."""
    raw = bytes.fromhex(hex_str)
    n = len(raw) // 4
    return list(struct.unpack(f"{n}f", raw))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Returns -1 to 1."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def find_duplicates(
    new_embedding: list[float],
    existing: list[tuple[str, list[float]]],
    threshold: float = 0.85,
) -> list[str]:
    """
    Find existing memory IDs that are duplicates of the new embedding.

    Args:
        new_embedding: The embedding to check.
        existing: List of (memory_id, embedding) tuples.
        threshold: Cosine similarity threshold (default 0.85).

    Returns:
        List of memory IDs that exceed the threshold.
    """
    duplicates = []
    for mem_id, emb in existing:
        if cosine_similarity(new_embedding, emb) >= threshold:
            duplicates.append(mem_id)
    return duplicates


def semantic_search(
    query_embedding: list[float],
    candidates: list[tuple[str, list[float]]],
    threshold: float = 0.3,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Find semantically similar memories.

    Args:
        query_embedding: Query vector.
        candidates: List of (memory_id, embedding) tuples.
        threshold: Minimum cosine similarity to include.
        top_k: Maximum results to return.

    Returns:
        List of (memory_id, score) sorted by score descending.
    """
    scores = []
    for mem_id, emb in candidates:
        score = cosine_similarity(query_embedding, emb)
        if score >= threshold:
            scores.append((mem_id, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]
