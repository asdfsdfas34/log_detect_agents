from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

try:
    import chromadb
except Exception:  # pragma: no cover - optional runtime dependency
    chromadb = None

_PATTERN_COLLECTION_V1 = "pattern_clusters"
_ANALYSIS_COLLECTION_V1 = "incident_analyses"
_PATTERN_COLLECTION_V2 = "pattern_templates_v2"
_CASE_CARD_COLLECTION_V2 = "case_cards_v2"
_KNOWN_PATTERN_COLLECTION_V2 = "known_patterns_v2"
_INCIDENT_SUMMARY_COLLECTION_V2 = "incident_summaries_v2"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
_DEFAULT_PATTERN_DIMENSIONS = 1024
_DEFAULT_CASE_CARD_DIMENSIONS = 1536


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


def _embedding_api_key() -> str:
    """Resolve the dedicated API key used only for vector embeddings."""

    return os.getenv("OPENAI_EMBEDDING_API_KEY", "").strip()


def _embedding_model() -> str:
    return os.getenv("OPENAI_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL).strip()


def _positive_int_env(name: str, default: int) -> int:
    try:
        parsed = int(os.getenv(name, ""))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _pattern_dimensions() -> int:
    return _positive_int_env(
        "OPENAI_PATTERN_EMBEDDING_DIMENSIONS",
        _positive_int_env("OPENAI_EMBEDDING_DIMENSIONS", _DEFAULT_PATTERN_DIMENSIONS),
    )


def _case_card_dimensions() -> int:
    return _positive_int_env(
        "OPENAI_CASE_CARD_EMBEDDING_DIMENSIONS",
        _positive_int_env("OPENAI_EMBEDDING_DIMENSIONS", _DEFAULT_CASE_CARD_DIMENSIONS),
    )


def _embedding_client() -> OpenAI | None:
    api_key = _embedding_api_key()
    if not api_key:
        return None
    base_url = (
        os.getenv("OPENAI_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
    )
    return OpenAI(api_key=api_key, base_url=base_url)


def _embed_text(text: str, *, dimensions: int) -> list[float] | None:
    client = _embedding_client()
    if client is None:
        return None
    response = client.embeddings.create(
        model=_embedding_model(), input=text, dimensions=dimensions
    )
    return list(response.data[0].embedding)


def _with_embedding_metadata(
    metadata: dict[str, Any] | None,
    *,
    document_type: str,
    schema_version: str,
    dimensions: int,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    merged.update(
        {
            "document_type": document_type,
            "schema_version": schema_version,
            "embedding_provider": "openai",
            "embedding_model": _embedding_model(),
            "embedding_dimensions": dimensions,
        }
    )
    return merged


def _upsert_document(
    *,
    collection_name: str,
    doc_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> bool:
    client = _client()
    if client is None:
        return False
    try:
        collection = client.get_or_create_collection(name=collection_name)
        upsert_kwargs: dict[str, Any] = {"ids": [doc_id], "documents": [text]}
        if metadata:
            upsert_kwargs["metadatas"] = [metadata]
        if embedding is not None:
            upsert_kwargs["embeddings"] = [embedding]
        collection.upsert(**upsert_kwargs)
        return True
    except Exception:
        return False


def _analysis_v2_target(doc_id: str) -> tuple[str, str, str, int]:
    if doc_id.startswith("knowledge-card:"):
        return (
            _CASE_CARD_COLLECTION_V2,
            "case_card",
            "case-card-v2",
            _case_card_dimensions(),
        )
    if doc_id.startswith("known-pattern:"):
        return (
            _KNOWN_PATTERN_COLLECTION_V2,
            "known_pattern",
            "known-pattern-v2",
            _case_card_dimensions(),
        )
    return (
        _INCIDENT_SUMMARY_COLLECTION_V2,
        "incident_summary",
        "incident-summary-v2",
        _case_card_dimensions(),
    )


def _query_collection(
    *, collection_name: str, query: str, n_results: int, dimensions: int | None = None
) -> dict[str, Any] | None:
    client = _client()
    if client is None:
        return None
    try:
        collection = client.get_or_create_collection(name=collection_name)
        query_kwargs: dict[str, Any] = {
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        embedding = _embed_text(query, dimensions=dimensions) if dimensions else None
        if embedding is not None:
            query_kwargs["query_embeddings"] = [embedding]
        else:
            query_kwargs["query_texts"] = [query]
        return collection.query(**query_kwargs)
    except Exception:
        return None


def _query_results(out: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not out:
        return []
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


def _save_analysis_document_v2(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    collection_name, document_type, schema_version, dimensions = _analysis_v2_target(
        doc_id
    )
    embedding = _embed_text(text, dimensions=dimensions)
    if embedding is None:
        return False
    return _upsert_document(
        collection_name=collection_name,
        doc_id=f"{schema_version}:{doc_id}",
        text=text,
        metadata=_with_embedding_metadata(
            metadata,
            document_type=document_type,
            schema_version=schema_version,
            dimensions=dimensions,
        ),
        embedding=embedding,
    )


def save_analysis_document(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    v1_saved = _upsert_document(
        collection_name=_ANALYSIS_COLLECTION_V1,
        doc_id=doc_id,
        text=text,
        metadata=metadata,
    )
    v2_saved = _save_analysis_document_v2(doc_id=doc_id, text=text, metadata=metadata)
    return v1_saved or v2_saved


def _pattern_template_text(text: str, metadata: dict[str, Any] | None) -> str:
    data = metadata or {}
    return "\n".join(
        [
            "[Pattern Template]",
            f"Service: {data.get('service_name', '-')}",
            f"Fingerprint: {data.get('fingerprint', '-')}",
            f"Log Level: {data.get('log_level', '-')}",
            f"Pattern Status: {data.get('pattern_status', '-')}",
            "",
            "[Normalized Message]",
            str(data.get("normalized_message") or "-"),
            "",
            "[Context]",
            text,
        ]
    )


def save_pattern_cluster(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    v1_saved = _upsert_document(
        collection_name=_PATTERN_COLLECTION_V1,
        doc_id=doc_id,
        text=text,
        metadata=metadata,
    )
    dimensions = _pattern_dimensions()
    v2_text = _pattern_template_text(text, metadata)
    embedding = _embed_text(v2_text, dimensions=dimensions)
    v2_saved = False
    if embedding is not None:
        v2_saved = _upsert_document(
            collection_name=_PATTERN_COLLECTION_V2,
            doc_id=f"pattern-template-v2:{doc_id}",
            text=v2_text,
            metadata=_with_embedding_metadata(
                metadata,
                document_type="pattern_template",
                schema_version="pattern-template-v2",
                dimensions=dimensions,
            ),
            embedding=embedding,
        )
    return v1_saved or v2_saved


def find_similar_pattern_clusters(
    *, query: str, n_results: int = 5
) -> list[dict[str, Any]]:
    dimensions = _pattern_dimensions() if _embedding_api_key() else None
    collection_name = _PATTERN_COLLECTION_V2 if dimensions else _PATTERN_COLLECTION_V1
    results = _query_results(
        _query_collection(
            collection_name=collection_name,
            query=query,
            n_results=n_results,
            dimensions=dimensions,
        )
    )
    if results or collection_name == _PATTERN_COLLECTION_V1:
        return results
    return _query_results(
        _query_collection(
            collection_name=_PATTERN_COLLECTION_V1, query=query, n_results=n_results
        )
    )


def find_related_analyses(*, query: str, n_results: int = 3) -> list[str]:
    dimensions = _case_card_dimensions() if _embedding_api_key() else None
    collection_names = (
        [
            _CASE_CARD_COLLECTION_V2,
            _KNOWN_PATTERN_COLLECTION_V2,
            _INCIDENT_SUMMARY_COLLECTION_V2,
        ]
        if dimensions
        else [_ANALYSIS_COLLECTION_V1]
    )
    related: list[str] = []
    for collection_name in collection_names:
        matches = _query_results(
            _query_collection(
                collection_name=collection_name,
                query=query,
                n_results=n_results,
                dimensions=dimensions,
            )
        )
        related.extend(str(match["document"]) for match in matches)
        if len(related) >= n_results:
            return related[:n_results]
    if related or not dimensions:
        return related[:n_results]
    matches = _query_results(
        _query_collection(
            collection_name=_ANALYSIS_COLLECTION_V1, query=query, n_results=n_results
        )
    )
    return [str(match["document"]) for match in matches[:n_results]]


def find_similar_analysis_documents(
    *, query: str, n_results: int = 5
) -> list[dict[str, Any]]:
    dimensions = _case_card_dimensions() if _embedding_api_key() else None
    collection_names = (
        [
            _CASE_CARD_COLLECTION_V2,
            _KNOWN_PATTERN_COLLECTION_V2,
            _INCIDENT_SUMMARY_COLLECTION_V2,
        ]
        if dimensions
        else [_ANALYSIS_COLLECTION_V1]
    )
    results: list[dict[str, Any]] = []
    for collection_name in collection_names:
        results.extend(
            _query_results(
                _query_collection(
                    collection_name=collection_name,
                    query=query,
                    n_results=n_results,
                    dimensions=dimensions,
                )
            )
        )
    if results or not dimensions:
        return sorted(
            results,
            key=lambda item: float(item.get("similarity") or 0),
            reverse=True,
        )[:n_results]
    return _query_results(
        _query_collection(
            collection_name=_ANALYSIS_COLLECTION_V1, query=query, n_results=n_results
        )
    )
