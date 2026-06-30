from __future__ import annotations

import logging
import os
from typing import Any

from openai import AzureOpenAI, OpenAI

from app.config import settings

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
_DEFAULT_EMBEDDING_BATCH_SIZE = 100

logger = logging.getLogger(__name__)


def _backend_logger() -> logging.Logger:
    uvicorn_logger = logging.getLogger("uvicorn.error")
    return uvicorn_logger if uvicorn_logger.handlers else logger


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

    if _embedding_provider() == "azure_openai":
        return _azure_embedding_api_key()
    return os.getenv("OPENAI_EMBEDDING_API_KEY", settings.openai_embedding_api_key).strip()


def _azure_embedding_api_key() -> str:
    return os.getenv(
        "AZURE_OPENAI_EMBEDDING_API_KEY", settings.azure_openai_embedding_api_key
    ).strip()


def _embedding_model() -> str:
    if _embedding_provider() == "azure_openai":
        return os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            settings.azure_openai_embedding_deployment,
        ).strip()
    return os.getenv("OPENAI_EMBEDDING_MODEL", settings.openai_embedding_model).strip()


def _embedding_provider() -> str:
    provider = os.getenv(
        "EMBEDDING_PROVIDER",
        os.getenv("OPENAI_EMBEDDING_PROVIDER", settings.embedding_provider),
    )
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"azure", "azure_openai"}:
        return "azure_openai"
    return "openai"


def _azure_embedding_endpoint() -> str:
    return (
        os.getenv(
            "AZURE_OPENAI_EMBEDDING_ENDPOINT",
            settings.azure_openai_embedding_endpoint,
        ).strip()
        or os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    )


def _azure_embedding_api_version() -> str:
    return os.getenv(
        "AZURE_OPENAI_EMBEDDING_API_VERSION",
        settings.azure_openai_embedding_api_version,
    ).strip() or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01").strip()


def _positive_int_env(name: str, default: int) -> int:
    try:
        parsed = int(os.getenv(name, ""))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _embedding_batch_size() -> int:
    return min(
        100,
        max(
            1,
            _positive_int_env(
                "OPENAI_EMBEDDING_BATCH_SIZE", _DEFAULT_EMBEDDING_BATCH_SIZE
            ),
        ),
    )


def _pattern_dimensions() -> int:
    return _positive_int_env(
        "OPENAI_PATTERN_EMBEDDING_DIMENSIONS",
        _positive_int_env(
            "OPENAI_EMBEDDING_DIMENSIONS",
            settings.openai_pattern_embedding_dimensions or _DEFAULT_PATTERN_DIMENSIONS,
        ),
    )


def _case_card_dimensions() -> int:
    return _positive_int_env(
        "OPENAI_CASE_CARD_EMBEDDING_DIMENSIONS",
        _positive_int_env(
            "OPENAI_EMBEDDING_DIMENSIONS",
            settings.openai_case_card_embedding_dimensions
            or _DEFAULT_CASE_CARD_DIMENSIONS,
        ),
    )


def _embedding_client() -> OpenAI | AzureOpenAI | None:
    api_key = _embedding_api_key()
    if not api_key:
        return None
    if _embedding_provider() == "azure_openai":
        azure_endpoint = _azure_embedding_endpoint()
        if not azure_endpoint or not _embedding_model():
            return None
        return AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=_azure_embedding_api_version(),
        )
    base_url = (
        os.getenv("OPENAI_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
    )
    return OpenAI(api_key=api_key, base_url=base_url)


def _embed_text(text: str, *, dimensions: int) -> list[float] | None:
    embeddings = _embed_texts([text], dimensions=dimensions)
    return embeddings[0] if embeddings else None


def _embed_texts(texts: list[str], *, dimensions: int) -> list[list[float]] | None:
    client = _embedding_client()
    if client is None:
        return None
    response = client.embeddings.create(
        model=_embedding_model(), input=texts, dimensions=dimensions
    )
    return [list(item.embedding) for item in response.data]


def _embed_texts_for_query(
    texts: list[str], *, dimensions: int
) -> list[list[float]] | None:
    try:
        return _embed_texts(texts, dimensions=dimensions)
    except Exception as exc:  # noqa: BLE001
        _backend_logger().warning("Embedding request failed; skipping vector query: %s", exc)
        return None


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
            "embedding_provider": _embedding_provider(),
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


def _upsert_documents(
    *,
    collection_name: str,
    ids: list[str],
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    embeddings: list[list[float]] | None = None,
) -> bool:
    client = _client()
    if client is None:
        return False
    try:
        collection = client.get_or_create_collection(name=collection_name)
        upsert_kwargs: dict[str, Any] = {"ids": ids, "documents": texts}
        if metadatas:
            upsert_kwargs["metadatas"] = metadatas
        if embeddings is not None:
            upsert_kwargs["embeddings"] = embeddings
        collection.upsert(**upsert_kwargs)
        return True
    except Exception:
        return False


def _delete_documents(*, collection_name: str, ids: list[str]) -> int:
    client = _client()
    if client is None or not ids:
        return 0
    try:
        collection = client.get_or_create_collection(name=collection_name)
        out = collection.get(ids=ids)
        existing_ids = [str(item) for item in out.get("ids", [])]
        if not existing_ids:
            return 0
        collection.delete(ids=existing_ids)
        return len(existing_ids)
    except Exception:
        return 0


def delete_pattern_clusters(doc_ids: list[str]) -> dict[str, int]:
    """Delete old pattern cluster documents from ChromaDB collections."""

    ids = [str(doc_id) for doc_id in doc_ids if doc_id]
    v1_deleted = _delete_documents(collection_name=_PATTERN_COLLECTION_V1, ids=ids)
    v2_deleted = _delete_documents(
        collection_name=_PATTERN_COLLECTION_V2,
        ids=[f"pattern-template-v2:{doc_id}" for doc_id in ids],
    )
    return {"v1_deleted": v1_deleted, "v2_deleted": v2_deleted}


def _existing_collection_ids(*, collection_name: str, ids: list[str]) -> set[str]:
    client = _client()
    if client is None or not ids:
        return set()
    try:
        collection = client.get_or_create_collection(name=collection_name)
        out = collection.get(ids=ids)
    except Exception:
        return set()
    return {str(item) for item in out.get("ids", [])}


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
    *,
    collection_name: str,
    query: str,
    n_results: int,
    dimensions: int | None = None,
    query_embeddings: list[list[float]] | None = None,
) -> dict[str, Any] | None:
    return _query_collection_batch(
        collection_name=collection_name,
        queries=[query],
        n_results=n_results,
        dimensions=dimensions,
        query_embeddings=query_embeddings,
    )


def _query_collection_batch(
    *,
    collection_name: str,
    queries: list[str],
    n_results: int,
    dimensions: int | None = None,
    query_embeddings: list[list[float]] | None = None,
) -> dict[str, Any] | None:
    client = _client()
    if client is None or not queries:
        return None
    try:
        collection = client.get_or_create_collection(name=collection_name)
        query_kwargs: dict[str, Any] = {
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        embeddings = (
            query_embeddings
            if query_embeddings is not None
            else _embed_texts_for_query(queries, dimensions=dimensions)
            if dimensions
            else None
        )
        if embeddings is not None:
            query_kwargs["query_embeddings"] = embeddings
        else:
            query_kwargs["query_texts"] = queries
        return collection.query(**query_kwargs)
    except Exception:
        return None


def _query_results(out: dict[str, Any] | None) -> list[dict[str, Any]]:
    groups = _query_result_groups(out)
    return groups[0] if groups else []


def _query_result_groups(out: dict[str, Any] | None) -> list[list[dict[str, Any]]]:
    if not out:
        return []
    docs = out.get("documents", [[]])
    metadatas = out.get("metadatas", [[]])
    distances = out.get("distances", [[]])
    ids = out.get("ids", [[]])
    groups: list[list[dict[str, Any]]] = []
    for query_index, documents in enumerate(docs or []):
        results: list[dict[str, Any]] = []
        query_metadatas = metadatas[query_index] if query_index < len(metadatas) else []
        query_distances = distances[query_index] if query_index < len(distances) else []
        query_ids = ids[query_index] if query_index < len(ids) else []
        for index, document in enumerate(documents or []):
            raw_distance = (
                query_distances[index]
                if index < len(query_distances) and query_distances[index] is not None
                else None
            )
            distance = float(raw_distance) if raw_distance is not None else None
            similarity = (
                None if distance is None else max(0.0, min(1.0, 1.0 - distance))
            )
            results.append(
                {
                    "id": query_ids[index] if index < len(query_ids) else "",
                    "document": str(document),
                    "metadata": (
                        query_metadatas[index] if index < len(query_metadatas) else {}
                    ),
                    "distance": distance,
                    "similarity": similarity,
                }
            )
        groups.append(results)
    return groups


def _save_analysis_document_v2(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    result = save_analysis_documents(
        [{"doc_id": doc_id, "text": text, "metadata": metadata or {}}]
    )
    return bool(result["v2_saved"] or result["v2_skipped"])


def save_analysis_document(
    *, doc_id: str, text: str, metadata: dict[str, Any] | None = None
) -> bool:
    result = save_analysis_documents(
        [{"doc_id": doc_id, "text": text, "metadata": metadata or {}}]
    )
    return bool(result["v1_saved"] or result["v2_saved"] or result["v2_skipped"])


def save_analysis_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist analysis documents, batching all v2 embedding calls by collection."""

    if not documents:
        return {"v1_saved": 0, "v2_saved": 0, "v2_skipped": 0, "v2_failed": []}

    v1_saved = _save_analysis_documents_v1(documents)
    if not _embedding_api_key():
        return {
            "v1_saved": v1_saved,
            "v2_saved": 0,
            "v2_skipped": 0,
            "v2_failed": [],
        }

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for document in documents:
        item = _analysis_document_v2_item(document)
        grouped.setdefault((str(item["collection_name"]), int(item["dimensions"])), [])
        grouped[(str(item["collection_name"]), int(item["dimensions"]))].append(item)

    saved = 0
    skipped = 0
    failed: list[dict[str, str]] = []
    batch_size = _embedding_batch_size()
    for (collection_name, dimensions), items in grouped.items():
        existing_ids = _existing_collection_ids(
            collection_name=collection_name,
            ids=[str(item["id"]) for item in items],
        )
        skipped += len(existing_ids)
        pending = [item for item in items if item["id"] not in existing_ids]
        for start in range(0, len(pending), batch_size):
            saved += _save_embedding_item_batch(
                collection_name=collection_name,
                items=pending[start : start + batch_size],
                dimensions=dimensions,
                failed=failed,
            )

    return {
        "v1_saved": v1_saved,
        "v2_saved": saved,
        "v2_skipped": skipped,
        "v2_failed": failed,
    }


def _save_analysis_documents_v1(documents: list[dict[str, Any]]) -> int:
    ids = [str(document["doc_id"]) for document in documents]
    texts = [str(document["text"]) for document in documents]
    metadatas = [dict(document.get("metadata") or {}) for document in documents]
    return (
        len(documents)
        if _upsert_documents(
            collection_name=_ANALYSIS_COLLECTION_V1,
            ids=ids,
            texts=texts,
            metadatas=metadatas,
        )
        else 0
    )


def _analysis_document_v2_item(document: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(document["doc_id"])
    collection_name, document_type, schema_version, dimensions = _analysis_v2_target(
        doc_id
    )
    metadata = _with_embedding_metadata(
        dict(document.get("metadata") or {}),
        document_type=document_type,
        schema_version=schema_version,
        dimensions=dimensions,
    )
    return {
        "collection_name": collection_name,
        "dimensions": dimensions,
        "id": f"{schema_version}:{doc_id}",
        "text": str(document["text"]),
        "metadata": metadata,
    }


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
    result = save_pattern_clusters(
        [{"doc_id": doc_id, "text": text, "metadata": metadata or {}}]
    )
    return bool(result["v1_saved"] or result["v2_saved"] or result["v2_skipped"])


def save_pattern_clusters(patterns: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist pattern clusters, batching v2 embeddings and skipping existing v2 ids."""

    if not patterns:
        return {"v1_saved": 0, "v2_saved": 0, "v2_skipped": 0, "v2_failed": []}

    v1_saved = _save_pattern_clusters_v1(patterns)
    dimensions = _pattern_dimensions()
    if not _embedding_api_key():
        return {
            "v1_saved": v1_saved,
            "v2_saved": 0,
            "v2_skipped": 0,
            "v2_failed": [],
        }

    v2_items = [_pattern_cluster_v2_item(pattern, dimensions) for pattern in patterns]
    existing_ids = _existing_collection_ids(
        collection_name=_PATTERN_COLLECTION_V2,
        ids=[str(item["id"]) for item in v2_items],
    )
    pending = [item for item in v2_items if item["id"] not in existing_ids]
    failed: list[dict[str, str]] = []
    saved = 0
    batch_size = _embedding_batch_size()
    total_batches = (len(pending) + batch_size - 1) // batch_size
    total_pending = len(pending)
    if total_batches == 0:
        _backend_logger().info(
            "Pattern embedding skipped: all %s pattern(s) already exist in v2",
            len(existing_ids),
        )
    for batch_index, start in enumerate(range(0, total_pending, batch_size), start=1):
        batch = pending[start : start + batch_size]
        _backend_logger().info(
            "Pattern embedding %s/%s running (items=%s, pending=%s, skipped=%s)",
            batch_index,
            total_batches,
            len(batch),
            total_pending,
            len(existing_ids),
        )
        before_failed = len(failed)
        saved_in_batch = _save_pattern_cluster_v2_batch(
            batch,
            dimensions=dimensions,
            failed=failed,
        )
        saved += saved_in_batch
        _backend_logger().info(
            "Pattern embedding %s/%s finished (saved=%s, failed=%s)",
            batch_index,
            total_batches,
            saved_in_batch,
            len(failed) - before_failed,
        )
    if total_batches > 0:
        _backend_logger().info(
            "Pattern embedding finished (batches=%s, saved=%s, skipped=%s, failed=%s)",
            total_batches,
            saved,
            len(existing_ids),
            len(failed),
        )
    return {
        "v1_saved": v1_saved,
        "v2_saved": saved,
        "v2_skipped": len(existing_ids),
        "v2_failed": failed,
    }


def _save_pattern_clusters_v1(patterns: list[dict[str, Any]]) -> int:
    ids = [str(pattern["doc_id"]) for pattern in patterns]
    texts = [str(pattern["text"]) for pattern in patterns]
    metadatas = [dict(pattern.get("metadata") or {}) for pattern in patterns]
    return (
        len(patterns)
        if _upsert_documents(
            collection_name=_PATTERN_COLLECTION_V1,
            ids=ids,
            texts=texts,
            metadatas=metadatas,
        )
        else 0
    )


def _pattern_cluster_v2_item(
    pattern: dict[str, Any], dimensions: int
) -> dict[str, Any]:
    metadata = dict(pattern.get("metadata") or {})
    text = str(pattern["text"])
    return {
        "id": f"pattern-template-v2:{pattern['doc_id']}",
        "text": _pattern_template_text(text, metadata),
        "metadata": _with_embedding_metadata(
            metadata,
            document_type="pattern_template",
            schema_version="pattern-template-v2",
            dimensions=dimensions,
        ),
    }


def _save_pattern_cluster_v2_batch(
    items: list[dict[str, Any]], *, dimensions: int, failed: list[dict[str, str]]
) -> int:
    if not items:
        return 0
    try:
        embeddings = _embed_texts(
            [str(item["text"]) for item in items], dimensions=dimensions
        )
        if embeddings is None:
            raise RuntimeError("embedding client is not configured")
        if len(embeddings) != len(items):
            raise RuntimeError(
                f"embedding response size mismatch: {len(embeddings)} != {len(items)}"
            )
        saved = _upsert_documents(
            collection_name=_PATTERN_COLLECTION_V2,
            ids=[str(item["id"]) for item in items],
            texts=[str(item["text"]) for item in items],
            metadatas=[dict(item["metadata"]) for item in items],
            embeddings=embeddings,
        )
        if not saved:
            raise RuntimeError("ChromaDB upsert failed")
        return len(items)
    except Exception as exc:  # noqa: BLE001
        if len(items) == 1:
            failed.append({"id": str(items[0]["id"]), "error": str(exc)})
            logger.warning(
                "Failed to save pattern embedding for %s: %s", items[0]["id"], exc
            )
            return 0
        midpoint = len(items) // 2
        return _save_pattern_cluster_v2_batch(
            items[:midpoint], dimensions=dimensions, failed=failed
        ) + _save_pattern_cluster_v2_batch(
            items[midpoint:], dimensions=dimensions, failed=failed
        )


def _save_embedding_item_batch(
    *,
    collection_name: str,
    items: list[dict[str, Any]],
    dimensions: int,
    failed: list[dict[str, str]],
) -> int:
    if not items:
        return 0
    try:
        embeddings = _embed_texts(
            [str(item["text"]) for item in items], dimensions=dimensions
        )
        if embeddings is None:
            raise RuntimeError("embedding client is not configured")
        if len(embeddings) != len(items):
            raise RuntimeError(
                f"embedding response size mismatch: {len(embeddings)} != {len(items)}"
            )
        saved = _upsert_documents(
            collection_name=collection_name,
            ids=[str(item["id"]) for item in items],
            texts=[str(item["text"]) for item in items],
            metadatas=[dict(item["metadata"]) for item in items],
            embeddings=embeddings,
        )
        if not saved:
            raise RuntimeError("ChromaDB upsert failed")
        return len(items)
    except Exception as exc:  # noqa: BLE001
        if len(items) == 1:
            failed.append({"id": str(items[0]["id"]), "error": str(exc)})
            logger.warning(
                "Failed to save embedding for %s in %s: %s",
                items[0]["id"],
                collection_name,
                exc,
            )
            return 0
        midpoint = len(items) // 2
        return _save_embedding_item_batch(
            collection_name=collection_name,
            items=items[:midpoint],
            dimensions=dimensions,
            failed=failed,
        ) + _save_embedding_item_batch(
            collection_name=collection_name,
            items=items[midpoint:],
            dimensions=dimensions,
            failed=failed,
        )


def find_similar_pattern_clusters(
    *, query: str, n_results: int = 5
) -> list[dict[str, Any]]:
    groups = find_similar_pattern_clusters_batch(queries=[query], n_results=n_results)
    return groups[0] if groups else []


def find_similar_pattern_clusters_batch(
    *, queries: list[str], n_results: int = 5
) -> list[list[dict[str, Any]]]:
    if not queries:
        return []
    dimensions = _pattern_dimensions() if _embedding_api_key() else None
    collection_name = _PATTERN_COLLECTION_V2 if dimensions else _PATTERN_COLLECTION_V1
    results = _query_pattern_collection_groups(
        collection_name=collection_name,
        queries=queries,
        n_results=n_results,
        dimensions=dimensions,
    )
    if not dimensions:
        return results
    missing_indexes = [index for index, group in enumerate(results) if not group]
    if not missing_indexes:
        return results
    fallback_groups = _query_pattern_collection_groups(
        collection_name=_PATTERN_COLLECTION_V1,
        queries=[queries[index] for index in missing_indexes],
        n_results=n_results,
    )
    for fallback_index, result_index in enumerate(missing_indexes):
        if fallback_index < len(fallback_groups):
            results[result_index] = fallback_groups[fallback_index]
    return results


def _query_pattern_collection_groups(
    *,
    collection_name: str,
    queries: list[str],
    n_results: int,
    dimensions: int | None = None,
    query_embeddings: list[list[float]] | None = None,
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = [[] for _ in queries]
    batch_size = _embedding_batch_size() if dimensions else len(queries)
    for start in range(0, len(queries), batch_size):
        batch = queries[start : start + batch_size]
        batch_embeddings = (
            query_embeddings[start : start + batch_size]
            if query_embeddings is not None
            else None
        )
        batch_groups = _query_result_groups(
            _query_collection_batch(
                collection_name=collection_name,
                queries=batch,
                n_results=n_results,
                dimensions=dimensions,
                query_embeddings=batch_embeddings,
            )
        )
        for offset, batch_result in enumerate(batch_groups):
            groups[start + offset] = batch_result
    return groups


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
    query_embedding = (
        _embed_texts_for_query([query], dimensions=dimensions) if dimensions else None
    )
    for collection_name in collection_names:
        matches = _query_results(
            _query_collection(
                collection_name=collection_name,
                query=query,
                n_results=n_results,
                dimensions=None if query_embedding else dimensions,
                query_embeddings=query_embedding,
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
    groups = find_similar_analysis_documents_batch(queries=[query], n_results=n_results)
    return groups[0] if groups else []


def find_similar_analysis_documents_batch(
    *, queries: list[str], n_results: int = 5
) -> list[list[dict[str, Any]]]:
    if not queries:
        return []
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
    groups: list[list[dict[str, Any]]] = [[] for _ in queries]
    shared_embeddings: list[list[float]] | None = None
    if dimensions:
        shared_embeddings = []
        batch_size = _embedding_batch_size()
        for start in range(0, len(queries), batch_size):
            embeddings = _embed_texts_for_query(
                queries[start : start + batch_size], dimensions=dimensions
            )
            if embeddings is None:
                shared_embeddings = None
                break
            shared_embeddings.extend(embeddings)
    for collection_name in collection_names:
        collection_groups = _query_pattern_collection_groups(
            collection_name=collection_name,
            queries=queries,
            n_results=n_results,
            dimensions=None if shared_embeddings is not None else dimensions,
            query_embeddings=shared_embeddings,
        )
        for index, collection_group in enumerate(collection_groups):
            groups[index].extend(collection_group)
    groups = [
        sorted(
            group,
            key=lambda item: float(item.get("similarity") or 0),
            reverse=True,
        )[:n_results]
        for group in groups
    ]
    if not dimensions:
        return groups

    missing_indexes = [index for index, group in enumerate(groups) if not group]
    if not missing_indexes:
        return groups
    fallback_groups = _query_pattern_collection_groups(
        collection_name=_ANALYSIS_COLLECTION_V1,
        queries=[queries[index] for index in missing_indexes],
        n_results=n_results,
    )
    for fallback_index, result_index in enumerate(missing_indexes):
        if fallback_index < len(fallback_groups):
            groups[result_index] = fallback_groups[fallback_index]
    return groups
