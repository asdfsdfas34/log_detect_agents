from __future__ import annotations

from typing import Any

from app.db import chroma_store
from app import main


class FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "ids": [["checkout-api:FP-OLD"]],
            "documents": [["service=checkout-api\nfingerprint=FP-OLD"]],
            "metadatas": [[{"fingerprint": "FP-OLD"}]],
            "distances": [[0.18]],
        }


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, name: str) -> FakeCollection:
        collection = self.collections.setdefault(name, FakeCollection())
        return collection


class FakeEmbeddingData:
    embedding = [0.1, 0.2, 0.3]


class FakeEmbeddingResponse:
    data = [FakeEmbeddingData()]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeEmbeddingResponse:
        self.calls.append(kwargs)
        return FakeEmbeddingResponse()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddings()


def test_pattern_cluster_chroma_uses_dedicated_collection(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)

    assert chroma_store.save_pattern_cluster(
        doc_id="checkout-api:FP-NEW",
        text="normalized message",
        metadata={"fingerprint": "FP-NEW"},
    )
    matches = chroma_store.find_similar_pattern_clusters(query="normalized message")

    assert "pattern_clusters" in client.collections
    assert client.collections["pattern_clusters"].upserts[0]["ids"] == [
        "checkout-api:FP-NEW"
    ]
    assert matches[0]["id"] == "checkout-api:FP-OLD"
    assert matches[0]["similarity"] == 0.8200000000000001


def test_pattern_cluster_v2_uses_dedicated_openai_embedding_key(monkeypatch) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_PATTERN_EMBEDDING_DIMENSIONS", "1024")

    assert chroma_store.save_pattern_cluster(
        doc_id="checkout-api:FP-NEW",
        text="service=checkout-api\nfingerprint=FP-NEW",
        metadata={
            "service_name": "checkout-api",
            "fingerprint": "FP-NEW",
            "log_level": "ERROR",
            "normalized_message": "Payment failed for order *",
        },
    )

    upsert = client.collections["pattern_templates_v2"].upserts[0]

    assert upsert["ids"] == ["pattern-template-v2:checkout-api:FP-NEW"]
    assert upsert["embeddings"] == [[0.1, 0.2, 0.3]]
    assert upsert["metadatas"][0]["embedding_model"] == "text-embedding-3-large"
    assert upsert["metadatas"][0]["embedding_dimensions"] == 1024
    assert embedding_client.embeddings.calls[0]["dimensions"] == 1024


def test_analysis_documents_route_to_v2_collections(monkeypatch) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")
    monkeypatch.setenv("OPENAI_CASE_CARD_EMBEDDING_DIMENSIONS", "1536")

    assert chroma_store.save_analysis_document(
        doc_id="knowledge-card:KC-123",
        text="[Case Card]\nresolution",
        metadata={"fingerprint": "FP-123"},
    )
    assert chroma_store.save_analysis_document(
        doc_id="known-pattern:7",
        text="[Known Pattern]\nknown",
        metadata={"fingerprint": "FP-456"},
    )

    assert "case_cards_v2" in client.collections
    assert "known_patterns_v2" in client.collections
    assert (
        client.collections["case_cards_v2"].upserts[0]["metadatas"][0]["document_type"]
        == "case_card"
    )
    assert (
        client.collections["known_patterns_v2"].upserts[0]["metadatas"][0][
            "document_type"
        ]
        == "known_pattern"
    )


def test_enrich_pattern_clusters_adds_backend_semantic_similarity(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)

    monkeypatch.setattr(
        main,
        "find_similar_pattern_clusters",
        chroma_store.find_similar_pattern_clusters,
    )
    monkeypatch.setattr(main, "save_pattern_cluster", chroma_store.save_pattern_cluster)

    clusters = main._enrich_pattern_clusters(
        service_name="checkout-api",
        fingerprints=[
            {
                "fingerprint": "FP-NEW",
                "occurrence_count": 3,
                "message": "Payment failed for order 123",
                "log_level": "ERROR",
                "stacktrace": "PaymentException",
            }
        ],
    )

    assert clusters[0]["cluster"] == "FP-NEW"
    assert clusters[0]["semantic_similarity"] == 82
    assert clusters[0]["similar_clusters"][0]["metadata"]["fingerprint"] == "FP-OLD"
    assert client.collections["pattern_clusters"].upserts[0]["ids"] == [
        "checkout-api:FP-NEW"
    ]
