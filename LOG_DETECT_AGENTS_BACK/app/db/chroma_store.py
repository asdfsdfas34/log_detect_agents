from __future__ import annotations

import os
from typing import Any

try:
    import chromadb
except Exception:  # pragma: no cover - optional runtime dependency
    chromadb = None


def _client():
    if chromadb is None:
        return None
    path = os.getenv("CHROMADB_PATH", "").strip()
    if not path:
        return None
    try:
        return chromadb.PersistentClient(path=path)
    except Exception:
        return None


def save_analysis_document(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    client = _client()
    if client is None:
        return False
    try:
        collection = client.get_or_create_collection(name="incident_analyses")
        upsert_kwargs: dict[str, Any] = {"ids": [doc_id], "documents": [text]}
        if metadata:
            upsert_kwargs["metadatas"] = [metadata]
        collection.upsert(**upsert_kwargs)
        return True
    except Exception:
        return False


def save_pattern_cluster(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    client = _client()
    if client is None:
        return False
    try:
        collection = client.get_or_create_collection(name="pattern_clusters")
        upsert_kwargs: dict[str, Any] = {"ids": [doc_id], "documents": [text]}
        if metadata:
            upsert_kwargs["metadatas"] = [metadata]
        collection.upsert(**upsert_kwargs)
        return True
    except Exception:
        return False


def find_similar_pattern_clusters(
    *, query: str, n_results: int = 5
) -> list[dict[str, Any]]:
    client = _client()
    if client is None:
        return []
    try:
        collection = client.get_or_create_collection(name="pattern_clusters")
        out = collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        docs = out.get("documents", [[]])
        metadatas = out.get("metadatas", [[]])
        distances = out.get("distances", [[]])
        ids = out.get("ids", [[]])
        results: list[dict[str, Any]] = []
        for index, document in enumerate(docs[0] if docs else []):
            distance = (
                float(distances[0][index])
                if distances and distances[0] and distances[0][index] is not None
                else None
            )
            similarity = None if distance is None else max(0.0, min(1.0, 1.0 - distance))
            results.append(
                {
                    "id": ids[0][index] if ids and ids[0] else "",
                    "document": str(document),
                    "metadata": metadatas[0][index] if metadatas and metadatas[0] else {},
                    "distance": distance,
                    "similarity": similarity,
                }
            )
        return results
    except Exception:
        return []


def find_related_analyses(*, query: str, n_results: int = 3) -> list[str]:
    client = _client()
    if client is None:
        return []
    try:
        collection = client.get_or_create_collection(name="incident_analyses")
        out = collection.query(query_texts=[query], n_results=n_results)
        docs = out.get("documents", [[]])
        return [str(item) for item in docs[0]] if docs else []
    except Exception:
        return []
