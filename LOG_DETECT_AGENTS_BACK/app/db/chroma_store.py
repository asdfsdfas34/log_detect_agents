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
