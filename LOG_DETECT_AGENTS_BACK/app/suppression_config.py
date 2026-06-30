"""Suppression rule configuration loader."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "suppression_rules.json"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@lru_cache(maxsize=1)
def get_suppression_config() -> dict[str, Any]:
    """Load suppression rules from JSON config, with an env override path."""

    config_path = Path(os.getenv("SUPPRESSION_CONFIG_PATH", str(_DEFAULT_CONFIG_PATH)))
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    patterns = []
    for item in _as_list(payload.get("known_patterns")):
        if not isinstance(item, dict):
            continue
        patterns.append(
            {
                "pattern_id": str(item.get("pattern_id", "")),
                "pattern": str(item.get("pattern", "")),
                "patterns": [str(value) for value in _as_list(item.get("patterns"))],
                "classification": str(item.get("classification", "unknown")),
                "suppression": bool(item.get("suppression", False)),
                "level_scope": [str(value).upper() for value in _as_list(item.get("level_scope"))],
                "stack_tokens": [str(value).lower() for value in _as_list(item.get("stack_tokens"))],
            }
        )

    anomaly = payload.get("anomaly_detection", {})
    if not isinstance(anomaly, dict):
        anomaly = {}

    return {
        "known_patterns": patterns,
        "anomaly_detection": {
            "suppressed_key_fields": [
                str(value) for value in _as_list(anomaly.get("suppressed_key_fields"))
            ]
            or ["timestamp", "system", "message"],
        },
    }


def clear_suppression_config_cache() -> None:
    """Clear cached config for tests that override SUPPRESSION_CONFIG_PATH."""

    get_suppression_config.cache_clear()
