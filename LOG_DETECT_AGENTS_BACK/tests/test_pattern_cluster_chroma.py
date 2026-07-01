from __future__ import annotations

import logging
from typing import Any

import pytest

from app import main
from app.db import chroma_store, scenario_store


class FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.existing_ids: set[str] = set()

    def upsert(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)
        self.existing_ids.update(str(item) for item in kwargs.get("ids", []))

    def get(self, **kwargs: Any) -> dict[str, Any]:
        ids = [str(item) for item in kwargs.get("ids", [])]
        return {"ids": [item for item in ids if item in self.existing_ids]}

    def delete(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)
        self.existing_ids.difference_update(str(item) for item in kwargs.get("ids", []))

    def query(self, **kwargs: Any) -> dict[str, Any]:
        queries = kwargs.get("query_embeddings") or kwargs.get("query_texts") or []
        count = len(queries) if isinstance(queries, list) else 1
        return {
            "ids": [["checkout-api:FP-OLD"] for _ in range(count)],
            "documents": [
                ["service=checkout-api\nfingerprint=FP-OLD"] for _ in range(count)
            ],
            "metadatas": [[{"fingerprint": "FP-OLD"}] for _ in range(count)],
            "distances": [[0.18] for _ in range(count)],
        }


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, name: str) -> FakeCollection:
        collection = self.collections.setdefault(name, FakeCollection())
        return collection


class FakeEmbeddingData:
    def __init__(self, embedding: list[float] | None = None) -> None:
        self.embedding = embedding or [0.1, 0.2, 0.3]


class FakeEmbeddingResponse:
    def __init__(self, count: int = 1) -> None:
        self.data = [FakeEmbeddingData() for _ in range(count)]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeEmbeddingResponse:
        self.calls.append(kwargs)
        input_value = kwargs.get("input", [])
        count = len(input_value) if isinstance(input_value, list) else 1
        return FakeEmbeddingResponse(count)


class FailingEmbeddings(FakeEmbeddings):
    def create(self, **kwargs: Any) -> FakeEmbeddingResponse:
        self.calls.append(kwargs)
        input_value = kwargs.get("input", [])
        count = len(input_value) if isinstance(input_value, list) else 1
        if count > 1 or any("bad-pattern" in str(item) for item in input_value):
            raise RuntimeError("embedding batch failed")
        return FakeEmbeddingResponse(count)


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddings()


class FakeOpenAIClientWithKwargs(FakeOpenAIClient):
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self.calls.append(kwargs)


class FailingOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = FailingEmbeddings()


class FakeAzureOpenAIClient(FakeOpenAIClient):
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def _clear_embedding_provider_env(monkeypatch) -> None:
    for name in [
        "EMBEDDING_PROVIDER",
        "OPENAI_EMBEDDING_PROVIDER",
        "AZURE_OPENAI_EMBEDDING_API_KEY",
        "AZURE_OPENAI_EMBEDDING_ENDPOINT",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_EMBEDDING_API_VERSION",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "OPENAI_BASE_URL",
        "OPENAI_EMBEDDING_BASE_URL",
    ]:
        monkeypatch.delenv(name, raising=False)


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


def test_delete_pattern_clusters_skips_missing_ids(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    client.get_or_create_collection("pattern_clusters").existing_ids.add(
        "checkout-api:FP-EXISTS"
    )
    client.get_or_create_collection("pattern_templates_v2").existing_ids.add(
        "pattern-template-v2:checkout-api:FP-EXISTS"
    )

    result = chroma_store.delete_pattern_clusters(
        ["checkout-api:FP-EXISTS", "checkout-api:FP-MISSING"]
    )

    assert result == {"v1_deleted": 1, "v2_deleted": 1}
    assert client.collections["pattern_clusters"].deletes == [
        {"ids": ["checkout-api:FP-EXISTS"]}
    ]
    assert client.collections["pattern_templates_v2"].deletes == [
        {"ids": ["pattern-template-v2:checkout-api:FP-EXISTS"]}
    ]


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
    assert embedding_client.embeddings.calls[0]["input"] == [
        "[Pattern Template]\n"
        "Service: checkout-api\n"
        "Fingerprint: FP-NEW\n"
        "Log Level: ERROR\n"
        "Pattern Status: -\n"
        "\n"
        "[Normalized Message]\n"
        "Payment failed for order *\n"
        "\n"
        "[Context]\n"
        "service=checkout-api\n"
        "fingerprint=FP-NEW"
    ]


def test_pattern_cluster_v2_batches_and_skips_existing_ids(monkeypatch) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")

    existing_collection = client.get_or_create_collection("pattern_templates_v2")
    existing_collection.existing_ids.add("pattern-template-v2:checkout-api:FP-1")

    result = chroma_store.save_pattern_clusters(
        [
            {
                "doc_id": "checkout-api:FP-1",
                "text": "pattern 1",
                "metadata": {"fingerprint": "FP-1"},
            },
            {
                "doc_id": "checkout-api:FP-2",
                "text": "pattern 2",
                "metadata": {"fingerprint": "FP-2"},
            },
            {
                "doc_id": "checkout-api:FP-3",
                "text": "pattern 3",
                "metadata": {"fingerprint": "FP-3"},
            },
        ]
    )

    assert result["v2_skipped"] == 1
    assert result["v2_saved"] == 2
    assert result["v2_failed"] == []
    assert len(embedding_client.embeddings.calls) == 1
    assert len(embedding_client.embeddings.calls[0]["input"]) == 2
    assert client.collections["pattern_templates_v2"].upserts[0]["ids"] == [
        "pattern-template-v2:checkout-api:FP-2",
        "pattern-template-v2:checkout-api:FP-3",
    ]


def test_pattern_cluster_v2_logs_embedding_batch_progress(
    monkeypatch, caplog
) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_BATCH_SIZE", "2")
    caplog.set_level(logging.INFO, logger=chroma_store.__name__)

    result = chroma_store.save_pattern_clusters(
        [
            {
                "doc_id": f"checkout-api:FP-{index}",
                "text": f"pattern {index}",
                "metadata": {"fingerprint": f"FP-{index}"},
            }
            for index in range(5)
        ]
    )

    messages = [record.getMessage() for record in caplog.records]

    assert result["v2_saved"] == 5
    assert len(embedding_client.embeddings.calls) == 3
    assert any("Pattern embedding 1/3 running" in message for message in messages)
    assert any("Pattern embedding 3/3 finished" in message for message in messages)
    assert any(
        "Pattern embedding finished (batches=3, saved=5" in message
        for message in messages
    )


def test_pattern_cluster_v2_splits_failed_batches_and_records_item_failure(
    monkeypatch,
) -> None:
    client = FakeClient()
    embedding_client = FailingOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")

    result = chroma_store.save_pattern_clusters(
        [
            {
                "doc_id": "checkout-api:good-pattern",
                "text": "good-pattern",
                "metadata": {"fingerprint": "good-pattern"},
            },
            {
                "doc_id": "checkout-api:bad-pattern",
                "text": "bad-pattern",
                "metadata": {"fingerprint": "bad-pattern"},
            },
        ]
    )

    assert result["v2_saved"] == 1
    assert result["v2_failed"] == [
        {
            "id": "pattern-template-v2:checkout-api:bad-pattern",
            "error": "embedding batch failed",
        }
    ]
    assert len(embedding_client.embeddings.calls) == 3


def test_pattern_cluster_v2_batch_query_uses_one_embedding_call(monkeypatch) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")

    matches = chroma_store.find_similar_pattern_clusters_batch(
        queries=["pattern 1", "pattern 2", "pattern 3"]
    )

    assert len(matches) == 3
    assert matches[0][0]["id"] == "checkout-api:FP-OLD"
    assert len(embedding_client.embeddings.calls) == 1
    assert embedding_client.embeddings.calls[0]["input"] == [
        "pattern 1",
        "pattern 2",
        "pattern 3",
    ]


def test_analysis_batch_query_reuses_one_embedding_call_across_collections(
    monkeypatch,
) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")

    matches = chroma_store.find_similar_analysis_documents_batch(
        queries=["case query 1", "case query 2"]
    )

    assert len(matches) == 2
    assert len(embedding_client.embeddings.calls) == 1
    assert embedding_client.embeddings.calls[0]["input"] == [
        "case query 1",
        "case query 2",
    ]
    assert {"case_cards_v2", "known_patterns_v2", "incident_summaries_v2"}.issubset(
        client.collections
    )


def test_find_related_analyses_reuses_one_embedding_call_across_collections(
    monkeypatch,
) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")

    related = chroma_store.find_related_analyses(query="incident query", n_results=3)

    assert related == [
        "service=checkout-api\nfingerprint=FP-OLD",
        "service=checkout-api\nfingerprint=FP-OLD",
        "service=checkout-api\nfingerprint=FP-OLD",
    ]
    assert len(embedding_client.embeddings.calls) == 1
    assert embedding_client.embeddings.calls[0]["input"] == ["incident query"]


def test_embedding_client_uses_azure_openai_when_configured(monkeypatch) -> None:
    FakeAzureOpenAIClient.calls = []
    monkeypatch.setattr(chroma_store, "AzureOpenAI", FakeAzureOpenAIClient)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_API_KEY", "azure-embedding-key")
    monkeypatch.setenv(
        "AZURE_OPENAI_EMBEDDING_ENDPOINT",
        "https://example-resource.openai.azure.com",
    )
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-02-01")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "embedding-deployment")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "legacy-openai-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

    client = chroma_store._embedding_client()

    assert isinstance(client, FakeAzureOpenAIClient)
    assert FakeAzureOpenAIClient.calls[0] == {
        "api_key": "azure-embedding-key",
        "azure_endpoint": "https://example-resource.openai.azure.com",
        "api_version": "2024-02-01",
    }
    assert chroma_store._embedding_model() == "embedding-deployment"
    assert chroma_store._embedding_provider() == "azure_openai"


def test_embedding_client_uses_openai_when_provider_is_openai(monkeypatch) -> None:
    FakeOpenAIClientWithKwargs.calls = []
    monkeypatch.setattr(chroma_store, "OpenAI", FakeOpenAIClientWithKwargs)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "openai-embedding-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_API_KEY", "azure-embedding-key")
    monkeypatch.setenv(
        "AZURE_OPENAI_EMBEDDING_ENDPOINT",
        "https://example-resource.openai.azure.com",
    )
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "embedding-deployment")

    client = chroma_store._embedding_client()

    assert isinstance(client, FakeOpenAIClientWithKwargs)
    assert FakeOpenAIClientWithKwargs.calls[0] == {
        "api_key": "openai-embedding-key",
        "base_url": None,
    }
    assert chroma_store._embedding_model() == "text-embedding-3-large"
    assert chroma_store._embedding_provider() == "openai"


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


def test_analysis_documents_v2_batch_by_collection_and_skip_existing(
    monkeypatch,
) -> None:
    client = FakeClient()
    embedding_client = FakeOpenAIClient()
    monkeypatch.setattr(chroma_store, "_client", lambda: client)
    monkeypatch.setattr(chroma_store, "_embedding_client", lambda: embedding_client)
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embedding-only-key")

    existing_collection = client.get_or_create_collection("case_cards_v2")
    existing_collection.existing_ids.add("case-card-v2:knowledge-card:KC-1")

    result = chroma_store.save_analysis_documents(
        [
            {
                "doc_id": "knowledge-card:KC-1",
                "text": "existing case",
                "metadata": {"fingerprint": "FP-1"},
            },
            {
                "doc_id": "knowledge-card:KC-2",
                "text": "new case",
                "metadata": {"fingerprint": "FP-2"},
            },
            {
                "doc_id": "known-pattern:7",
                "text": "known pattern",
                "metadata": {"fingerprint": "FP-3"},
            },
        ]
    )

    assert result["v2_skipped"] == 1
    assert result["v2_saved"] == 2
    assert result["v2_failed"] == []
    assert len(embedding_client.embeddings.calls) == 2
    assert client.collections["case_cards_v2"].upserts[0]["ids"] == [
        "case-card-v2:knowledge-card:KC-2"
    ]
    assert client.collections["known_patterns_v2"].upserts[0]["ids"] == [
        "known-pattern-v2:known-pattern:7"
    ]


def test_enrich_pattern_clusters_skips_similarity_by_default(monkeypatch) -> None:
    called = False

    def fake_similar_batches(**kwargs: Any) -> list[list[dict[str, Any]]]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(main, "find_similar_pattern_clusters_batch", fake_similar_batches)
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
    assert clusters[0]["semantic_similarity"] == 0
    assert clusters[0]["similar_clusters"] == []
    assert called is False


def test_enrich_pattern_clusters_adds_backend_semantic_similarity(monkeypatch) -> None:
    def fake_similar_batches(**kwargs: Any) -> list[list[dict[str, Any]]]:
        return [
            [
                {
                    "id": "checkout-api:FP-OLD",
                    "document": "service=checkout-api\nfingerprint=FP-OLD",
                    "metadata": {"fingerprint": "FP-OLD"},
                    "similarity": 0.82,
                }
            ]
        ]

    monkeypatch.setattr(main, "find_similar_pattern_clusters_batch", fake_similar_batches)
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
        include_similar_clusters=True,
    )

    assert clusters[0]["cluster"] == "FP-NEW"
    assert clusters[0]["semantic_similarity"] == 82
    assert clusters[0]["similar_clusters"][0]["metadata"]["fingerprint"] == "FP-OLD"


def test_save_new_pattern_clusters_only_persists_new_patterns(monkeypatch) -> None:
    saved_documents: list[dict[str, Any]] = []

    def fake_save_pattern_clusters(patterns: list[dict[str, Any]]) -> dict[str, Any]:
        saved_documents.extend(patterns)
        return {"v1_saved": len(patterns), "v2_saved": 0, "v2_skipped": 0, "v2_failed": []}

    monkeypatch.setattr(scenario_store, "save_pattern_clusters", fake_save_pattern_clusters)
    result = scenario_store.save_new_pattern_clusters(
        [
            {
                "service_name": "checkout-api",
                "fingerprint": "FP-NEW",
                "normalized_message": "payment failed",
                "message": "Payment failed",
                "log_level": "ERROR",
                "stacktrace": "",
                "occurrence_count": 3,
                "pattern_status": "new_pattern",
            },
            {
                "service_name": "checkout-api",
                "fingerprint": "FP-OLD",
                "normalized_message": "payment failed",
                "message": "Payment failed",
                "log_level": "ERROR",
                "stacktrace": "",
                "occurrence_count": 9,
                "pattern_status": "known_exact",
            },
        ]
    )

    assert result is not None
    assert [doc["doc_id"] for doc in saved_documents] == ["checkout-api:FP-NEW"]


def test_save_new_pattern_clusters_skips_empty_save(monkeypatch) -> None:
    called = False

    def fake_save_pattern_clusters(patterns: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"v1_saved": len(patterns), "v2_saved": 0, "v2_skipped": 0, "v2_failed": []}

    monkeypatch.setattr(scenario_store, "save_pattern_clusters", fake_save_pattern_clusters)
    result = scenario_store.save_new_pattern_clusters(
        [
            {
                "service_name": "checkout-api",
                "fingerprint": "FP-OLD",
                "normalized_message": "payment failed",
                "message": "Payment failed",
                "log_level": "ERROR",
                "stacktrace": "",
                "occurrence_count": 9,
                "pattern_status": "known_exact",
            }
        ]
    )

    assert result is None
    assert called is False
