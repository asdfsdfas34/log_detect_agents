from __future__ import annotations

import os
from typing import List

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


def save_analysis_document(*, doc_id: str, text: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        collection = client.get_or_create_collection(name="incident_analyses")
        collection.upsert(ids=[doc_id], documents=[text])
    except Exception:
        return


def find_related_analyses(*, query: str, n_results: int = 3) -> List[str]:
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
