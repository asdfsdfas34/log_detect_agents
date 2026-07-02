"""Typed PatternOps contract models.

PatternOps treats log patterns as operational knowledge assets: each pattern has
matching preconditions, an operation, produced artifacts, validators, failure
modes, and lifecycle metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PatternContract:
    """Operational contract for one known log/error/response pattern."""

    pattern_id: str
    name: str
    category: str
    sub_category: str
    lifecycle: str
    confidence: str
    precondition: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    validators: list[dict[str, Any]] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    source: str = "pattern_contracts"


@dataclass(frozen=True)
class PatternContractMatch:
    """A scored PatternOps contract match for a log or fingerprint."""

    pattern_id: str
    name: str
    category: str
    sub_category: str
    lifecycle: str
    confidence: float
    matched_by: list[str]
    operation: dict[str, Any]
    artifact: dict[str, Any]
    validators: list[dict[str, Any]]
    failure_modes: list[str]
