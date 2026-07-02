"""SQLite-backed PatternOps registry and compatibility adapters."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from difflib import SequenceMatcher
from typing import Any

from app.db.sqlite_store import _resolve_db_path
from app.patternops.contracts import PatternContract, PatternContractMatch

ACTIVE_LIFECYCLES = {"draft", "active", "monitor"}
DEFAULT_SCHEMA_VERSION = "patternops-v1"


def _json_dict(value: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _json_list(value: str | None) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def ensure_patternops_schema(conn: sqlite3.Connection) -> None:
    """Create PatternOps registry tables without touching service_logs."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pattern_contracts (
            pattern_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Unknown',
            sub_category TEXT NOT NULL DEFAULT 'Unknown',
            lifecycle TEXT NOT NULL DEFAULT 'active',
            confidence TEXT NOT NULL DEFAULT 'MID',
            precondition_json TEXT NOT NULL DEFAULT '{}',
            operation_json TEXT NOT NULL DEFAULT '{}',
            artifact_json TEXT NOT NULL DEFAULT '{}',
            failure_modes_json TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'manual',
            source_ref TEXT NOT NULL DEFAULT '',
            schema_version TEXT NOT NULL DEFAULT 'patternops-v1',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pattern_contract_edges (
            edge_id TEXT PRIMARY KEY,
            from_pattern_id TEXT NOT NULL,
            to_pattern_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_pattern_id, to_pattern_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS pattern_contract_validators (
            validator_id TEXT PRIMARY KEY,
            pattern_id TEXT NOT NULL,
            validator_type TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pattern_ops_actions (
            action_id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            pattern_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'proposed',
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    from app.patternops.skill_graph import bootstrap_default_skill_graphs

    bootstrap_default_skill_graphs(conn)


def _contract_from_row(
    row: sqlite3.Row | tuple[Any, ...],
    validators_by_pattern: dict[str, list[dict[str, Any]]] | None = None,
) -> PatternContract:
    validators_by_pattern = validators_by_pattern or {}
    pattern_id = str(row["pattern_id"])
    return PatternContract(
        pattern_id=pattern_id,
        name=str(row["name"] or ""),
        category=str(row["category"] or "Unknown"),
        sub_category=str(row["sub_category"] or "Unknown"),
        lifecycle=str(row["lifecycle"] or "active"),
        confidence=str(row["confidence"] or "MID"),
        precondition=_json_dict(row["precondition_json"]),
        operation=_json_dict(row["operation_json"]),
        artifact=_json_dict(row["artifact_json"]),
        validators=validators_by_pattern.get(pattern_id, []),
        failure_modes=[str(item) for item in _json_list(row["failure_modes_json"])],
        source=str(row["source"] or "pattern_contracts"),
    )


def _load_validators(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    validators: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute(
        """
        SELECT pattern_id, validator_id, validator_type, config_json
        FROM pattern_contract_validators
        WHERE enabled=1
        ORDER BY created_at ASC, validator_id ASC
        """
    ).fetchall()
    for row in rows:
        validators.setdefault(str(row["pattern_id"]), []).append(
            {
                "validator_id": str(row["validator_id"]),
                "validator_type": str(row["validator_type"]),
                "config": _json_dict(row["config_json"]),
            }
        )
    return validators


def fetch_pattern_contracts_for_agents(limit: int = 500) -> list[PatternContract]:
    """Return active PatternOps contracts for deterministic agents."""

    db_path = _resolve_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        ensure_patternops_schema(conn)
        sync_pattern_contracts_from_legacy_tables(conn)
        validators = _load_validators(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM pattern_contracts
            WHERE lifecycle IN ('draft', 'active', 'monitor')
            ORDER BY
                CASE lifecycle WHEN 'active' THEN 0 WHEN 'monitor' THEN 1 ELSE 2 END,
                datetime(updated_at) DESC,
                pattern_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_contract_from_row(row, validators) for row in rows]


def lookup_pattern_contracts(
    *,
    message: str,
    normalized_message: str,
    level: str,
    fingerprint: str,
    service_name: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find PatternOps contracts that can explain one log event."""

    matches: list[PatternContractMatch] = []
    for contract in fetch_pattern_contracts_for_agents():
        score = 0.0
        reasons: list[str] = []
        precondition = contract.precondition
        artifact = contract.artifact

        if str(artifact.get("fingerprint") or "") == fingerprint:
            score += 0.95
            reasons.append("fingerprint")

        service_scope = {
            str(item) for item in precondition.get("service_scope", []) if str(item)
        }
        if service_scope:
            if service_name in service_scope:
                score += 0.15
                reasons.append("service_scope")
            else:
                score -= 0.25

        level_scope = {
            str(item).upper() for item in precondition.get("level_scope", []) if str(item)
        }
        if level_scope and level.upper() in level_scope:
            score += 0.10
            reasons.append("level_scope")

        template = str(precondition.get("message_template") or "")
        if template:
            normalized_template = template.strip().lower()
            if normalized_template and normalized_template in normalized_message:
                score += 0.45
                reasons.append("template")
            similarity = SequenceMatcher(
                None, normalized_message, normalized_template
            ).ratio()
            if similarity >= 0.86:
                score += 0.25
                reasons.append("template_similarity")

        match_regex = str(precondition.get("match_regex") or "")
        if match_regex:
            try:
                if re.search(match_regex, message, flags=re.IGNORECASE):
                    score += 0.50
                    reasons.append("regex")
            except re.error:
                score -= 0.10
                reasons.append("invalid_regex")

        for keyword in precondition.get("keywords", []):
            keyword_text = str(keyword).strip().lower()
            if keyword_text and keyword_text in normalized_message:
                score += 0.12
                reasons.append("keyword")
                break

        if score >= 0.45:
            matches.append(
                PatternContractMatch(
                    pattern_id=contract.pattern_id,
                    name=contract.name,
                    category=contract.category,
                    sub_category=contract.sub_category,
                    lifecycle=contract.lifecycle,
                    confidence=round(min(score, 0.99), 2),
                    matched_by=reasons,
                    operation=contract.operation,
                    artifact=contract.artifact,
                    validators=contract.validators,
                    failure_modes=contract.failure_modes,
                )
            )

    matches.sort(key=lambda item: item.confidence, reverse=True)
    return [
        {
            "pattern_id": match.pattern_id,
            "name": match.name,
            "category": match.category,
            "sub_category": match.sub_category,
            "lifecycle": match.lifecycle,
            "confidence": match.confidence,
            "matched_by": match.matched_by,
            "operation": match.operation,
            "artifact": match.artifact,
            "validators": match.validators,
            "failure_modes": match.failure_modes,
        }
        for match in matches[:limit]
    ]


def sync_pattern_contracts_from_legacy_tables(
    conn: sqlite3.Connection | None = None,
) -> int:
    """Mirror approved legacy knowledge into PatternOps contracts.

    This keeps existing screens and tests intact while exposing old
    known_patterns, normalization rules, and knowledge cards as registry assets.
    """

    owns_connection = conn is None
    if conn is None:
        conn = sqlite3.connect(_resolve_db_path())
    conn.row_factory = sqlite3.Row
    ensure_patternops_schema(conn)
    inserted = 0
    try:
        try:
            known_pattern_rows = conn.execute(
                """
                SELECT id, fingerprint, category, sub_category, cause, recommendation, confidence
                FROM known_patterns
                ORDER BY id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            known_pattern_rows = []
        for row in known_pattern_rows:
            pattern_id = f"KP-{int(row['id']):06d}"
            fingerprint = str(row["fingerprint"] or "")
            sub_category = str(row["sub_category"] or "Known Pattern")
            _upsert_contract(
                conn,
                pattern_id=pattern_id,
                name=sub_category,
                category=str(row["category"] or "Known Pattern"),
                sub_category=sub_category,
                confidence=str(row["confidence"] or "HIGH"),
                precondition={
                    "fingerprint": fingerprint,
                    "message_template": sub_category,
                    "keywords": [sub_category, str(row["cause"] or "")],
                },
                operation={
                    "analysis_type": "known_pattern",
                    "root_cause": str(row["cause"] or ""),
                    "recommended_actions": [str(row["recommendation"] or "")],
                },
                artifact={
                    "fingerprint": fingerprint,
                    "known_pattern_id": int(row["id"]),
                },
                failure_modes=[
                    "stale recommendation after service behavior changes",
                    "similar logs may require a different root cause",
                ],
                source="known_patterns",
                source_ref=str(row["id"]),
            )
            _upsert_validator(
                conn,
                pattern_id=pattern_id,
                validator_type="fingerprint_or_similarity",
                config={"min_confidence": 0.45, "fingerprint": fingerprint},
            )
            inserted += 1

        try:
            normalization_rule_rows = conn.execute(
                """
                SELECT id, name, match_regex, template, enabled, priority
                FROM pattern_normalization_rules
                ORDER BY id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            normalization_rule_rows = []
        for row in normalization_rule_rows:
            if int(row["enabled"] or 0) != 1:
                continue
            rule_id = int(row["id"])
            template = str(row["template"] or "")
            _upsert_contract(
                conn,
                pattern_id=f"NR-{rule_id:06d}",
                name=str(row["name"] or f"normalization-rule-{rule_id}"),
                category="Normalization",
                sub_category="Fingerprint Normalization",
                confidence="HIGH",
                precondition={
                    "match_regex": str(row["match_regex"] or ""),
                    "message_template": template,
                    "keywords": [template],
                },
                operation={
                    "analysis_type": "normalize_then_match",
                    "normalization_template": template,
                    "priority": int(row["priority"] or 100),
                },
                artifact={
                    "normalization_rule_id": rule_id,
                    "template": template,
                },
                failure_modes=[
                    "over-broad regex can merge unrelated fingerprints",
                    "template may hide meaningful runtime values",
                ],
                source="pattern_normalization_rules",
                source_ref=str(rule_id),
            )
            _upsert_validator(
                conn,
                pattern_id=f"NR-{rule_id:06d}",
                validator_type="regex_match",
                config={"match_regex": str(row["match_regex"] or "")},
            )
            inserted += 1

        try:
            knowledge_card_rows = conn.execute(
                """
                SELECT card_id, fingerprint, title, cause, recommendation, confidence,
                       root_cause, remediation_steps, verification_steps, prevention_steps
                FROM knowledge_cards
                ORDER BY created_at ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            knowledge_card_rows = []
        for row in knowledge_card_rows:
            card_id = str(row["card_id"])
            remediation_steps = [
                str(item) for item in _json_list(row["remediation_steps"])
            ]
            verification_steps = [
                str(item) for item in _json_list(row["verification_steps"])
            ]
            _upsert_contract(
                conn,
                pattern_id=f"KC-{card_id}",
                name=str(row["title"] or f"Knowledge Card {card_id}"),
                category="KnowledgeCard",
                sub_category="Approved Case",
                confidence=str(row["confidence"] or "HIGH"),
                precondition={
                    "fingerprint": str(row["fingerprint"] or ""),
                    "keywords": [str(row["cause"] or ""), str(row["root_cause"] or "")],
                },
                operation={
                    "analysis_type": "approved_case_card",
                    "root_cause": str(row["root_cause"] or row["cause"] or ""),
                    "recommended_actions": remediation_steps
                    or [str(row["recommendation"] or "")],
                    "verification_steps": verification_steps,
                    "prevention_steps": [
                        str(item) for item in _json_list(row["prevention_steps"])
                    ],
                },
                artifact={
                    "fingerprint": str(row["fingerprint"] or ""),
                    "knowledge_card_id": card_id,
                },
                failure_modes=["approved resolution may not apply to new topology"],
                source="knowledge_cards",
                source_ref=card_id,
            )
            inserted += 1
        conn.commit()
    finally:
        if owns_connection:
            conn.close()
    return inserted


def _upsert_contract(
    conn: sqlite3.Connection,
    *,
    pattern_id: str,
    name: str,
    category: str,
    sub_category: str,
    confidence: str,
    precondition: dict[str, Any],
    operation: dict[str, Any],
    artifact: dict[str, Any],
    failure_modes: list[str],
    source: str,
    source_ref: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pattern_contracts(
            pattern_id, name, category, sub_category, lifecycle, confidence,
            precondition_json, operation_json, artifact_json, failure_modes_json,
            source, source_ref, schema_version
        ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pattern_id) DO UPDATE SET
            name=excluded.name,
            category=excluded.category,
            sub_category=excluded.sub_category,
            confidence=excluded.confidence,
            precondition_json=excluded.precondition_json,
            operation_json=excluded.operation_json,
            artifact_json=excluded.artifact_json,
            failure_modes_json=excluded.failure_modes_json,
            source=excluded.source,
            source_ref=excluded.source_ref,
            schema_version=excluded.schema_version,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            pattern_id,
            name,
            category,
            sub_category,
            confidence,
            _dump(precondition),
            _dump(operation),
            _dump(artifact),
            _dump(failure_modes),
            source,
            source_ref,
            DEFAULT_SCHEMA_VERSION,
        ),
    )


def _upsert_validator(
    conn: sqlite3.Connection,
    *,
    pattern_id: str,
    validator_type: str,
    config: dict[str, Any],
) -> None:
    validator_id = f"{pattern_id}:{validator_type}"
    conn.execute(
        """
        INSERT INTO pattern_contract_validators(
            validator_id, pattern_id, validator_type, config_json, enabled
        ) VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(validator_id) DO UPDATE SET
            config_json=excluded.config_json,
            enabled=1
        """,
        (validator_id, pattern_id, validator_type, _dump(config)),
    )


def record_pattern_ops_action(
    *,
    action_type: str,
    pattern_id: str = "",
    status: str = "proposed",
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    reason: str = "",
) -> str:
    """Persist an auditable PatternOps maintenance action."""

    digest = hashlib.sha1(_dump(payload or {}).encode("utf-8")).hexdigest()[:12]
    action_id = f"{action_type}:{pattern_id or 'global'}:{digest}"
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_patternops_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO pattern_ops_actions(
                action_id, action_type, pattern_id, status, payload_json,
                result_json, reason, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                action_id,
                action_type,
                pattern_id,
                status,
                _dump(payload or {}),
                _dump(result or {}),
                reason,
            ),
        )
        conn.commit()
    return action_id
