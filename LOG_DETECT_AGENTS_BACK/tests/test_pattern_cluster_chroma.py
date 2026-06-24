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


def test_enrich_pattern_clusters_adds_backend_semantic_similarity(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)

    monkeypatch.setattr(main, "find_similar_pattern_clusters", chroma_store.find_similar_pattern_clusters)
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
