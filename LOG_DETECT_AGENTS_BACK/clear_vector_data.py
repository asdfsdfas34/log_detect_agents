"""Delete ChromaDB vector collections without touching SQLite data."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

try:
    import chromadb
except Exception as exc:  # pragma: no cover - import guard for CLI use
    chromadb = None
    CHROMADB_IMPORT_ERROR = exc
else:
    CHROMADB_IMPORT_ERROR = None


KNOWN_COLLECTIONS = [
    "pattern_clusters",
    "incident_analyses",
    "pattern_templates_v2",
    "case_cards_v2",
    "known_patterns_v2",
    "incident_summaries_v2",
]


def _collection_name(collection: Any) -> str:
    if isinstance(collection, str):
        return collection
    return str(getattr(collection, "name", collection))


def _resolve_chromadb_path(raw_path: str | None) -> Path:
    value = (raw_path or os.getenv("CHROMADB_PATH") or "./.chroma").strip()
    path = Path(value)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def _client(path: Path):
    if chromadb is None:
        raise RuntimeError(f"chromadb import failed: {CHROMADB_IMPORT_ERROR}")
    return chromadb.PersistentClient(path=str(path))


def list_collection_names(client: Any) -> list[str]:
    return sorted(_collection_name(collection) for collection in client.list_collections())


def clear_vector_data(*, chromadb_path: Path, apply: bool, clear_all: bool) -> list[str]:
    client = _client(chromadb_path)
    existing = set(list_collection_names(client))
    target_names = sorted(existing if clear_all else existing.intersection(KNOWN_COLLECTIONS))
    if apply:
        for name in target_names:
            client.delete_collection(name=name)
    return target_names


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete ChromaDB vector collections without changing SQLite."
    )
    parser.add_argument(
        "--chromadb-path",
        default=None,
        help="ChromaDB path. Defaults to CHROMADB_PATH or ./.chroma.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete every collection in the ChromaDB path, not just known app collections.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete collections. Without this flag, only prints a dry-run summary.",
    )
    args = parser.parse_args()

    chromadb_path = _resolve_chromadb_path(args.chromadb_path)
    if not chromadb_path.exists():
        raise FileNotFoundError(f"ChromaDB path not found: {chromadb_path}")

    collections = clear_vector_data(
        chromadb_path=chromadb_path,
        apply=args.yes,
        clear_all=args.all,
    )
    mode = "deleted" if args.yes else "would delete"
    scope = "all collections" if args.all else "known app collections"
    print(f"ChromaDB: {chromadb_path}")
    print(f"Scope: {scope}")
    if not collections:
        print("No matching collections found.")
    for name in collections:
        print(f"{mode} collection {name}")
    if not args.yes:
        print("Dry run only. Re-run with --yes to delete vector data.")


if __name__ == "__main__":
    main()
