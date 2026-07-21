"""SkillOps-style graph-of-graphs registry and planner for PatternOps."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.db.sqlite_store import _resolve_db_path

SKILL_SCHEMA_VERSION = "patternops-skill-v1"
EXCLUDED_SKILL_IDS = {"impact_evaluation"}
SCOPE_CATEGORIES = {
    "log_collection": {"ingestion"},
    "log_analysis": {"normalization", "fingerprint", "matching", "maintenance"},
    "anomaly_detection": {"detection", "guard"},
    "recommendation": {"retrieval", "recommendation", "knowledge_capture"},
    "maintenance": {"maintenance", "normalization", "knowledge_capture"},
}


@dataclass(frozen=True)
class PatternSkill:
    """A selectable operational skill represented as a small graph."""

    skill_id: str
    name: str
    category: str
    lifecycle: str
    priority: int
    graph: dict[str, Any] = field(default_factory=dict)
    precondition: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    validators: list[dict[str, Any]] = field(default_factory=list)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


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


DEFAULT_SKILLS: list[dict[str, Any]] = [
    {
        "skill_id": "log_collection",
        "name": "Log Collection Skill",
        "category": "ingestion",
        "priority": 10,
        "requires": ["service_scope"],
        "produces": ["normalized_logs", "stack_traces"],
        "operation_type": "agent",
        "operation_ref": "LogCollectorAgent",
        "validators": ["non_empty_or_fallback_logs", "service_scope_match"],
    },
    {
        "skill_id": "log_normalization",
        "name": "Log Normalization Skill",
        "category": "normalization",
        "priority": 20,
        "requires": ["raw_log_message"],
        "produces": ["normalized_message", "normalization_rule_match"],
        "operation_type": "function",
        "operation_ref": "normalize_log_text",
        "validators": ["regex_compile", "sample_before_after"],
    },
    {
        "skill_id": "pattern_fingerprint",
        "name": "Pattern Fingerprint Skill",
        "category": "fingerprint",
        "priority": 30,
        "requires": ["normalized_message"],
        "produces": ["fingerprint", "occurrence_count"],
        "operation_type": "function",
        "operation_ref": "fingerprint_id",
        "validators": ["stable_fingerprint", "occurrence_count_preserved"],
    },
    {
        "skill_id": "known_pattern_match",
        "name": "Known Pattern Match Skill",
        "category": "matching",
        "priority": 40,
        "requires": ["fingerprint_or_template"],
        "produces": ["known_pattern_matches", "pattern_ops_matches"],
        "operation_type": "planner",
        "operation_ref": "lookup_pattern_contracts",
        "validators": ["confidence_threshold", "match_source_present"],
    },
    {
        "skill_id": "duplicate_pattern_detection",
        "name": "Duplicate Pattern Detection Skill",
        "category": "maintenance",
        "priority": 70,
        "requires": ["fingerprint_groups"],
        "produces": ["duplicate_pattern_candidates"],
        "operation_type": "function",
        "operation_ref": "detect_duplicate_pattern_candidates",
        "validators": ["similarity_threshold", "variable_token_ratio"],
    },
    {
        "skill_id": "fingerprint_merge",
        "name": "Fingerprint Merge Skill",
        "category": "maintenance",
        "priority": 80,
        "requires": ["approved_duplicate_candidate"],
        "produces": ["canonical_fingerprint", "fingerprint_aliases"],
        "operation_type": "function",
        "operation_ref": "merge_duplicate_pattern_candidate",
        "validators": ["alias_created", "occurrence_count_preserved"],
    },
    {
        "skill_id": "anomaly_detection",
        "name": "Anomaly Detection Skill",
        "category": "detection",
        "priority": 50,
        "requires": ["fingerprint_time_series"],
        "produces": ["anomalies", "anomaly_daily_counts"],
        "operation_type": "agent",
        "operation_ref": "AnomalyDetectionAgent",
        "validators": ["baseline_comparison", "severity_reason"],
    },
    {
        "skill_id": "knowledge_card_retrieval",
        "name": "Knowledge Card Retrieval Skill",
        "category": "retrieval",
        "priority": 90,
        "requires": ["fingerprint_or_root_cause_hint"],
        "produces": ["related_case_cards"],
        "operation_type": "function",
        "operation_ref": "fetch_knowledge_cards",
        "validators": ["fingerprint_match", "confidence_present"],
    },
    {
        "skill_id": "chroma_similar_pattern_retrieval",
        "name": "Chroma Similar Pattern Retrieval Skill",
        "category": "retrieval",
        "priority": 95,
        "requires": ["pattern_context_query"],
        "produces": ["similar_clusters", "related_knowledge"],
        "operation_type": "vector_query",
        "operation_ref": "find_similar_pattern_clusters_batch",
        "validators": ["similarity_score", "schema_version"],
    },
    {
        "skill_id": "recommendation_generation",
        "name": "Recommendation Generation Skill",
        "category": "recommendation",
        "priority": 110,
        "requires": ["analysis_evidence"],
        "produces": [
            "recommendation_candidate",
            "recommended_actions",
            "verification_steps",
        ],
        "operation_type": "agent",
        "operation_ref": "RecommendationAgent",
        "validators": ["evidence_linked_actions", "owner_present"],
    },
    {
        "skill_id": "recommendation_quality_gate",
        "name": "Recommendation Quality Gate Skill",
        "category": "recommendation",
        "priority": 120,
        "requires": ["recommendation_candidate"],
        "produces": ["quality_score", "quality_feedback"],
        "operation_type": "validator",
        "operation_ref": "RecommendationAgent._evaluate_recommendation",
        "validators": ["minimum_quality_score", "hard_fail_checks"],
    },
    {
        "skill_id": "exception_suppression",
        "name": "Exception Suppression Skill",
        "category": "guard",
        "priority": 65,
        "requires": ["fingerprint", "reason"],
        "produces": ["suppressed_logs", "exception_registry"],
        "operation_type": "function",
        "operation_ref": "register_exception",
        "validators": ["fingerprint_exists", "reason_present"],
    },
    {
        "skill_id": "pattern_rule_suggestion",
        "name": "Pattern Rule Suggestion Skill",
        "category": "maintenance",
        "priority": 75,
        "requires": ["sample_message"],
        "produces": ["match_regex", "template"],
        "operation_type": "agent",
        "operation_ref": "PatternRuleSuggestionAgent",
        "validators": ["regex_compile", "sample_match"],
    },
    {
        "skill_id": "resolution_capture",
        "name": "Resolution Capture Skill",
        "category": "knowledge_capture",
        "priority": 130,
        "requires": ["approved_resolution"],
        "produces": ["knowledge_card", "rag_document"],
        "operation_type": "function",
        "operation_ref": "approve_result",
        "validators": ["required_fields", "embedding_status"],
    },
]


DEFAULT_SKILL_EDGES: list[dict[str, Any]] = [
    ("log_collection", "log_normalization", "dependency"),
    ("log_normalization", "pattern_fingerprint", "dependency"),
    ("pattern_fingerprint", "known_pattern_match", "dependency"),
    ("pattern_fingerprint", "duplicate_pattern_detection", "downstream"),
    ("duplicate_pattern_detection", "fingerprint_merge", "approval_required"),
    ("known_pattern_match", "knowledge_card_retrieval", "alternative"),
    ("known_pattern_match", "chroma_similar_pattern_retrieval", "alternative"),
    ("known_pattern_match", "anomaly_detection", "dependency"),
    ("exception_suppression", "anomaly_detection", "guard"),
    ("anomaly_detection", "recommendation_generation", "dependency"),
    ("knowledge_card_retrieval", "recommendation_generation", "dependency"),
    ("chroma_similar_pattern_retrieval", "recommendation_generation", "dependency"),
    ("recommendation_generation", "recommendation_quality_gate", "dependency"),
    ("recommendation_quality_gate", "resolution_capture", "approval_required"),
    ("pattern_rule_suggestion", "log_normalization", "adapter"),
]


def _skill_graph_for(skill: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "precondition", "type": "precondition", "requires": skill["requires"]},
            {
                "id": "operation",
                "type": skill["operation_type"],
                "ref": skill["operation_ref"],
            },
            {"id": "artifact", "type": "artifact", "produces": skill["produces"]},
            {"id": "validator", "type": "validator", "checks": skill["validators"]},
        ],
        "edges": [
            {"from": "precondition", "to": "operation", "type": "enables"},
            {"from": "operation", "to": "artifact", "type": "produces"},
            {"from": "artifact", "to": "validator", "type": "validates"},
        ],
    }


def ensure_skill_graph_schema(conn: sqlite3.Connection) -> None:
    """Create SkillOps graph-of-graphs tables."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pattern_skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            lifecycle TEXT NOT NULL DEFAULT 'active',
            priority INTEGER NOT NULL DEFAULT 100,
            graph_json TEXT NOT NULL DEFAULT '{}',
            precondition_json TEXT NOT NULL DEFAULT '{}',
            operation_json TEXT NOT NULL DEFAULT '{}',
            artifact_json TEXT NOT NULL DEFAULT '{}',
            validators_json TEXT NOT NULL DEFAULT '[]',
            schema_version TEXT NOT NULL DEFAULT 'patternops-skill-v1',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pattern_skill_edges (
            edge_id TEXT PRIMARY KEY,
            from_skill_id TEXT NOT NULL,
            to_skill_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_skill_id, to_skill_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS pattern_skill_executions (
            execution_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            agent_name TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT '',
            skill_id TEXT NOT NULL,
            status TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            input_refs_json TEXT NOT NULL DEFAULT '[]',
            output_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    execution_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(pattern_skill_executions)")
    ]
    for column, definition in {
        "agent_name": "TEXT NOT NULL DEFAULT ''",
        "scope": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in execution_columns:
            conn.execute(
                f"ALTER TABLE pattern_skill_executions ADD COLUMN {column} {definition}"
            )
    conn.commit()


def bootstrap_default_skill_graphs(conn: sqlite3.Connection | None = None) -> None:
    """Register built-in PatternOps skills, excluding Impact Evaluation."""

    owns_connection = conn is None
    if conn is None:
        conn = sqlite3.connect(_resolve_db_path())
    try:
        ensure_skill_graph_schema(conn)
        for skill in DEFAULT_SKILLS:
            if skill["skill_id"] in EXCLUDED_SKILL_IDS:
                continue
            conn.execute(
                """
                INSERT INTO pattern_skills(
                    skill_id, name, category, lifecycle, priority, graph_json,
                    precondition_json, operation_json, artifact_json, validators_json,
                    schema_version
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    lifecycle='active',
                    priority=excluded.priority,
                    graph_json=excluded.graph_json,
                    precondition_json=excluded.precondition_json,
                    operation_json=excluded.operation_json,
                    artifact_json=excluded.artifact_json,
                    validators_json=excluded.validators_json,
                    schema_version=excluded.schema_version,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    skill["skill_id"],
                    skill["name"],
                    skill["category"],
                    int(skill["priority"]),
                    _dump(_skill_graph_for(skill)),
                    _dump({"requires": skill["requires"]}),
                    _dump(
                        {
                            "operation_type": skill["operation_type"],
                            "operation_ref": skill["operation_ref"],
                        }
                    ),
                    _dump({"produces": skill["produces"]}),
                    _dump(
                        [
                            {"validator_type": validator, "enabled": True}
                            for validator in skill["validators"]
                        ]
                    ),
                    SKILL_SCHEMA_VERSION,
                ),
            )
        conn.execute(
            "UPDATE pattern_skills SET lifecycle='retired' WHERE skill_id=?",
            ("impact_evaluation",),
        )
        for from_skill, to_skill, edge_type in DEFAULT_SKILL_EDGES:
            if from_skill in EXCLUDED_SKILL_IDS or to_skill in EXCLUDED_SKILL_IDS:
                continue
            edge_id = f"{from_skill}:{edge_type}:{to_skill}"
            conn.execute(
                """
                INSERT INTO pattern_skill_edges(
                    edge_id, from_skill_id, to_skill_id, edge_type, weight, reason
                ) VALUES (?, ?, ?, ?, 1.0, ?)
                ON CONFLICT(from_skill_id, to_skill_id, edge_type) DO UPDATE SET
                    weight=excluded.weight,
                    reason=excluded.reason
                """,
                (
                    edge_id,
                    from_skill,
                    to_skill,
                    edge_type,
                    f"default {edge_type} relation",
                ),
            )
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def fetch_pattern_skills(limit: int = 200) -> list[PatternSkill]:
    """Return active registered skill graphs."""

    with sqlite3.connect(_resolve_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        bootstrap_default_skill_graphs(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM pattern_skills
            WHERE lifecycle IN ('active', 'monitor')
              AND skill_id != 'impact_evaluation'
            ORDER BY priority ASC, skill_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        PatternSkill(
            skill_id=str(row["skill_id"]),
            name=str(row["name"]),
            category=str(row["category"]),
            lifecycle=str(row["lifecycle"]),
            priority=int(row["priority"]),
            graph=_json_dict(row["graph_json"]),
            precondition=_json_dict(row["precondition_json"]),
            operation=_json_dict(row["operation_json"]),
            artifact=_json_dict(row["artifact_json"]),
            validators=[
                item for item in _json_list(row["validators_json"]) if isinstance(item, dict)
            ],
        )
        for row in rows
    ]


def fetch_pattern_skill_edges() -> list[dict[str, Any]]:
    """Return graph-of-graphs relationships between registered skills."""

    with sqlite3.connect(_resolve_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        bootstrap_default_skill_graphs(conn)
        rows = conn.execute(
            """
            SELECT edge_id, from_skill_id, to_skill_id, edge_type, weight, reason
            FROM pattern_skill_edges
            WHERE from_skill_id != 'impact_evaluation'
              AND to_skill_id != 'impact_evaluation'
            ORDER BY edge_type ASC, from_skill_id ASC, to_skill_id ASC
            """
        ).fetchall()
    return [
        {
            "edge_id": str(row["edge_id"]),
            "from_skill_id": str(row["from_skill_id"]),
            "to_skill_id": str(row["to_skill_id"]),
            "edge_type": str(row["edge_type"]),
            "weight": float(row["weight"]),
            "reason": str(row["reason"]),
        }
        for row in rows
    ]


def plan_skill_graphs(
    state: dict[str, Any], *, scope: str | None = None
) -> dict[str, Any]:
    """Select skill graphs based on current evidence and skill relationships."""

    skills = fetch_pattern_skills()
    skill_by_id = {skill.skill_id: skill for skill in skills}
    if scope:
        allowed_categories = SCOPE_CATEGORIES.get(scope, set())
        skills = [
            skill
            for skill in skills
            if skill.category in allowed_categories or skill.skill_id == scope
        ]
        skill_by_id = {skill.skill_id: skill for skill in skills}
    edges = fetch_pattern_skill_edges()
    skill_ids = {skill.skill_id for skill in skills}
    scoped_edges = [
        edge
        for edge in edges
        if edge["from_skill_id"] in skill_ids and edge["to_skill_id"] in skill_ids
    ]
    evidence = state.get("evidence", {})
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    precondition_decisions: list[dict[str, Any]] = []

    for skill in skills:
        score, reasons = _score_skill(skill.skill_id, evidence, state)
        precondition = evaluate_skill_precondition(skill, state)
        precondition_decisions.append(
            {
                "skill_id": skill.skill_id,
                "passed": precondition["passed"],
                "satisfied": precondition["satisfied"],
                "missing": precondition["missing"],
                "reason": precondition["reason"],
            }
        )
        item = {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "category": skill.category,
            "priority": skill.priority,
            "score": score,
            "reasons": [*reasons, precondition["reason"]],
            "graph": skill.graph,
            "precondition": skill.precondition,
            "precondition_eval": precondition,
            "operation": skill.operation,
            "artifact": skill.artifact,
            "validators": skill.validators,
        }
        if score > 0 and precondition["passed"]:
            selected.append(item)
            selected_ids.add(skill.skill_id)
        else:
            skipped.append(item)

    selected, skipped, edge_decisions = execute_skill_edges(
        selected=selected,
        skipped=skipped,
        edges=scoped_edges,
        skill_by_id=skill_by_id,
        state=state,
    )

    selected.sort(key=lambda item: (float(item["score"]) * -1, str(item["skill_id"])))
    selected = _dedupe_plan(selected)
    return {
        "selected_skills": selected,
        "skipped_skills": skipped,
        "skill_edges": scoped_edges,
        "precondition_decisions": precondition_decisions,
        "edge_decisions": edge_decisions,
        "excluded_skills": sorted(EXCLUDED_SKILL_IDS),
        "scope": scope or "global",
    }


def evaluate_skill_precondition(
    skill: PatternSkill, state: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate a skill precondition against the current SharedState snapshot."""

    required = [
        str(item)
        for item in skill.precondition.get("requires", [])
        if str(item).strip()
    ]
    satisfied: list[str] = []
    missing: list[str] = []
    for requirement in required:
        if _requirement_satisfied(requirement, state):
            satisfied.append(requirement)
        else:
            missing.append(requirement)
    passed = not missing
    return {
        "passed": passed,
        "satisfied": satisfied,
        "missing": missing,
        "reason": (
            "precondition_passed"
            if passed
            else f"precondition_missing:{','.join(missing)}"
        ),
    }


def execute_skill_edges(
    *,
    selected: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    skill_by_id: dict[str, PatternSkill],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply graph-of-graphs edge semantics to the selected skill set."""

    selected_by_id = {str(item.get("skill_id")): item for item in selected}
    skipped_by_id = {str(item.get("skill_id")): item for item in skipped}
    decisions: list[dict[str, Any]] = []

    for edge in edges:
        edge_type = str(edge.get("edge_type", ""))
        from_skill_id = str(edge.get("from_skill_id", ""))
        to_skill_id = str(edge.get("to_skill_id", ""))
        from_selected = from_skill_id in selected_by_id
        to_selected = to_skill_id in selected_by_id
        action = "observed"
        reason = f"{edge_type}:{from_skill_id}->{to_skill_id}"

        if edge_type == "dependency" and to_selected and not from_selected:
            dependency = skill_by_id.get(from_skill_id)
            if dependency is not None:
                selected_by_id[from_skill_id] = _edge_selected_item(
                    dependency,
                    score=0.5,
                    reasons=[f"dependency_for:{to_skill_id}"],
                    state=state,
                )
                skipped_by_id.pop(from_skill_id, None)
                action = "selected_upstream_dependency"
        elif edge_type == "dependency" and from_selected and not to_selected:
            target = skill_by_id.get(to_skill_id)
            if target is not None and _edge_can_satisfy_target(
                source=skill_by_id.get(from_skill_id),
                target=target,
            ):
                selected_by_id[to_skill_id] = _edge_selected_item(
                    target,
                    score=0.5,
                    reasons=[f"dependency_after:{from_skill_id}"],
                    state=state,
                )
                skipped_by_id.pop(to_skill_id, None)
                action = "selected_downstream_dependency"
        elif edge_type == "guard" and from_selected and to_selected:
            selected_by_id[to_skill_id]["reasons"] = [
                *selected_by_id[to_skill_id].get("reasons", []),
                f"guard_checked:{from_skill_id}",
            ]
            action = "guard_checked"
        elif edge_type == "alternative" and from_selected:
            action = "alternative_available" if to_selected else "alternative_not_ready"
        elif edge_type == "approval_required":
            action = "approval_required"
        elif edge_type == "adapter":
            action = "adapter_available" if from_selected or to_selected else "observed"

        decisions.append(
            {
                "edge_id": edge.get("edge_id"),
                "from_skill_id": from_skill_id,
                "to_skill_id": to_skill_id,
                "edge_type": edge_type,
                "action": action,
                "reason": reason,
            }
        )

    return list(selected_by_id.values()), list(skipped_by_id.values()), decisions


def _edge_selected_item(
    skill: PatternSkill,
    *,
    score: float,
    reasons: list[str],
    state: dict[str, Any],
) -> dict[str, Any]:
    precondition = evaluate_skill_precondition(skill, state)
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "category": skill.category,
        "priority": skill.priority,
        "score": score,
        "reasons": [*reasons, precondition["reason"]],
        "graph": skill.graph,
        "precondition": skill.precondition,
        "precondition_eval": precondition,
        "operation": skill.operation,
        "artifact": skill.artifact,
        "validators": skill.validators,
    }


def _edge_can_satisfy_target(
    *, source: PatternSkill | None, target: PatternSkill
) -> bool:
    if source is None:
        return False
    produced = set(target.artifact.get("produces", []))
    produced.update(source.artifact.get("produces", []))
    required = set(target.precondition.get("requires", []))
    return any(_artifact_matches_requirement(artifact, requirement) for artifact in produced for requirement in required)


def _artifact_matches_requirement(artifact: str, requirement: str) -> bool:
    direct_matches = {
        "service_scope": {"service_scope"},
        "raw_log_message": {"normalized_logs", "raw_log_message"},
        "normalized_message": {"normalized_message", "message_template"},
        "fingerprint_or_template": {
            "fingerprint",
            "normalized_message",
            "message_template",
        },
        "fingerprint_groups": {"fingerprint", "occurrence_count"},
        "approved_duplicate_candidate": {"canonical_fingerprint"},
        "fingerprint_time_series": {
            "fingerprint",
            "occurrence_count",
            "anomaly_daily_counts",
        },
        "fingerprint_or_root_cause_hint": {
            "fingerprint",
            "known_pattern_matches",
            "incident_candidates",
        },
        "pattern_context_query": {"similar_clusters", "related_knowledge", "anomalies"},
        "analysis_evidence": {
            "anomalies",
            "known_pattern_matches",
            "pattern_ops_matches",
            "recommendation_candidate",
        },
        "recommendation_candidate": {
            "recommendation_candidate",
            "recommended_actions",
            "verification_steps",
        },
        "fingerprint": {"fingerprint"},
        "reason": {"reason"},
        "sample_message": {"sample_message", "normalized_message"},
        "approved_resolution": {"knowledge_card", "rag_document"},
    }
    return artifact in direct_matches.get(requirement, {requirement})


def _requirement_satisfied(requirement: str, state: dict[str, Any]) -> bool:
    evidence = state.get("evidence", {})
    final = state.get("final", {}) or {}
    scope = state.get("scope", {}) or {}

    if requirement == "service_scope":
        return bool(scope.get("systems"))
    if requirement == "raw_log_message":
        return bool(evidence.get("normalized_logs"))
    if requirement == "normalized_message":
        return any(
            str(item.get("message_template") or item.get("message") or "").strip()
            for item in evidence.get("normalized_logs", [])
            if isinstance(item, dict)
        )
    if requirement == "fingerprint_or_template":
        return any(
            str(
                item.get("fingerprint")
                or item.get("message_template")
                or item.get("message")
                or ""
            ).strip()
            for item in evidence.get("normalized_logs", [])
            if isinstance(item, dict)
        ) or bool(evidence.get("pattern_ops_matches"))
    if requirement == "fingerprint_groups":
        return bool(
            evidence.get("duplicate_pattern_candidates")
            or evidence.get("clusters")
            # The scoped runner executes Pattern Fingerprint (priority 30)
            # before Duplicate Pattern Detection (priority 70), so collected
            # logs are a valid upstream source for this planned artifact.
            or evidence.get("normalized_logs")
            or any(
                item.get("fingerprint")
                for item in evidence.get("normalized_logs", [])
                if isinstance(item, dict)
            )
        )
    if requirement == "approved_duplicate_candidate":
        return any(
            str(item.get("status", "pending")) == "approved"
            for item in evidence.get("duplicate_pattern_candidates", [])
            if isinstance(item, dict)
        )
    if requirement == "fingerprint_time_series":
        return bool(
            evidence.get("anomaly_daily_counts")
            or evidence.get("clusters")
            or evidence.get("normalized_logs")
        )
    if requirement == "fingerprint_or_root_cause_hint":
        return bool(
            evidence.get("known_pattern_matches")
            or evidence.get("incident_candidates")
            or scope.get("filters", {}).get("fingerprint")
        )
    if requirement == "pattern_context_query":
        return bool(
            evidence.get("clusters")
            or evidence.get("anomalies")
            or evidence.get("normalized_logs")
        )
    if requirement == "analysis_evidence":
        return bool(
            evidence.get("anomalies")
            or evidence.get("known_pattern_matches")
            or evidence.get("pattern_ops_matches")
            or evidence.get("incident_candidates")
        )
    if requirement == "recommendation_candidate":
        return bool(
            evidence.get("recommendation_candidate")
            or final.get("recommended_actions")
        )
    if requirement == "fingerprint":
        return bool(
            scope.get("filters", {}).get("fingerprint")
            or evidence.get("suppressed_logs")
            or any(
                item.get("fingerprint")
                for item in evidence.get("normalized_logs", [])
                if isinstance(item, dict)
            )
        )
    if requirement == "reason":
        return bool(evidence.get("suppressed_logs") or evidence.get("recommendation"))
    if requirement == "sample_message":
        return bool(evidence.get("new_pattern_candidates") or evidence.get("normalized_logs"))
    if requirement == "approved_resolution":
        return bool(final.get("generated_answer"))
    return bool(evidence.get(requirement) or final.get(requirement))


def record_skill_executions(
    *,
    request_id: str,
    plan: dict[str, Any],
    agent_name: str = "",
    scope: str = "",
    status: str = "planned",
) -> list[dict[str, Any]]:
    """Persist selected skill graph executions."""

    executions: list[dict[str, Any]] = []
    with sqlite3.connect(_resolve_db_path()) as conn:
        bootstrap_default_skill_graphs(conn)
        for item in plan.get("selected_skills", []):
            skill_id = str(item.get("skill_id", ""))
            execution_id = f"{request_id}:{agent_name}:{scope}:{skill_id}:{status}"
            input_refs = item.get("graph", {}).get("nodes", [{}])[0].get("requires", [])
            output_refs = item.get("artifact", {}).get("produces", [])
            row = {
                "execution_id": execution_id,
                "request_id": request_id,
                "agent_name": agent_name,
                "scope": scope or str(plan.get("scope", "")),
                "skill_id": skill_id,
                "status": status,
                "score": float(item.get("score", 0)),
                "reason": ", ".join(str(reason) for reason in item.get("reasons", [])),
                "input_refs": input_refs,
                "output_refs": output_refs,
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO pattern_skill_executions(
                    execution_id, request_id, agent_name, scope, skill_id, status,
                    score, reason, input_refs_json, output_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["execution_id"],
                    row["request_id"],
                    row["agent_name"],
                    row["scope"],
                    row["skill_id"],
                    row["status"],
                    row["score"],
                    row["reason"],
                    _dump(input_refs),
                    _dump(output_refs),
                ),
            )
            executions.append(row)
        conn.commit()
    return executions


def _score_skill(
    skill_id: str, evidence: dict[str, Any], state: dict[str, Any]
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if skill_id == "log_collection":
        score = 1.0
        reasons.append("entrypoint")
    elif skill_id == "log_normalization" and evidence.get("normalized_logs"):
        score = 0.95
        reasons.append("logs_available")
    elif skill_id == "pattern_fingerprint" and evidence.get("normalized_logs"):
        score = 0.9
        reasons.append("normalized_logs_available")
    elif skill_id == "known_pattern_match" and (
        evidence.get("normalized_logs") or evidence.get("pattern_ops_matches")
    ):
        score = 0.9
        reasons.append("fingerprint_or_template_available")
    elif skill_id == "duplicate_pattern_detection" and evidence.get("normalized_logs"):
        score = 0.85
        reasons.append("fingerprint_source_logs_available")
    elif skill_id == "fingerprint_merge" and any(
        str(item.get("status", "pending")) == "approved"
        for item in evidence.get("duplicate_pattern_candidates", [])
    ):
        score = 0.8
        reasons.append("approved_duplicate_candidate_available")
    elif skill_id == "anomaly_detection" and (
        evidence.get("normalized_logs") or evidence.get("clusters")
    ):
        score = 0.85
        reasons.append("fingerprints_or_logs_available")
    elif skill_id == "knowledge_card_retrieval" and (
        evidence.get("known_pattern_matches") or evidence.get("incident_candidates")
    ):
        score = 0.78
        reasons.append("known_pattern_or_incident_hint_available")
    elif skill_id == "chroma_similar_pattern_retrieval" and (
        evidence.get("clusters") or evidence.get("anomalies")
    ):
        score = 0.72
        reasons.append("pattern_context_available")
    elif skill_id == "recommendation_generation" and (
        evidence.get("anomalies")
        or evidence.get("known_pattern_matches")
        or evidence.get("pattern_ops_matches")
    ):
        score = 0.76
        reasons.append("analysis_evidence_available")
    elif skill_id == "recommendation_quality_gate" and (
        state.get("final", {}).get("recommended_actions")
        or evidence.get("recommendation_candidate")
        or evidence.get("anomalies")
        or evidence.get("known_pattern_matches")
        or evidence.get("pattern_ops_matches")
    ):
        score = 0.7
        reasons.append("recommendation_candidate_available")
    elif skill_id == "exception_suppression" and evidence.get("suppressed_logs"):
        score = 0.66
        reasons.append("suppressed_logs_available")
    elif skill_id == "pattern_rule_suggestion" and evidence.get(
        "new_pattern_candidates"
    ):
        score = 0.64
        reasons.append("new_pattern_candidates_available")
    elif skill_id == "resolution_capture" and state.get("final", {}).get(
        "generated_answer"
    ):
        score = 0.62
        reasons.append("final_answer_available_for_approval")
    return score, reasons


def _dedupe_plan(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        skill_id = str(item.get("skill_id", ""))
        existing = deduped.get(skill_id)
        if existing is None or float(item.get("score", 0)) > float(
            existing.get("score", 0)
        ):
            deduped[skill_id] = item
    return list(deduped.values())
