import json

from app.agents.anomaly_detection import AnomalyDetectionAgent
from app.agents.impact_evaluation import ImpactEvaluationAgent
from app.agents.log_analysis import LogAnalysisAgent
from app.state import create_initial_state
from app.suppression_config import clear_suppression_config_cache


class FakeMCPClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, tool_name, arguments=None):
        self.calls.append((tool_name, arguments or {}))
        if tool_name == "sqlite.fetch_latest_log_analyses":
            return []
        if tool_name == "sqlite.save_impact_evaluation":
            return None
        raise AssertionError(f"unexpected tool: {tool_name}")


def _write_config(path, *, credit_per_log=5, max_credit=15):
    path.write_text(
        json.dumps(
            {
                "known_patterns": [
                    {
                        "pattern_id": "KP-CUSTOM-NOISY-001",
                        "pattern": "custom noisy dependency",
                        "patterns": ["custom noisy dependency"],
                        "classification": "false_positive",
                        "suppression": True,
                        "level_scope": ["WARN"],
                    }
                ],
                "anomaly_detection": {
                    "suppressed_key_fields": ["system", "message"],
                },
                "impact_evaluation": {
                    "credit_per_suppressed_log": credit_per_log,
                    "max_suppression_credit": max_credit,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_log_analysis_uses_suppression_patterns_from_config(tmp_path, monkeypatch):
    config_path = tmp_path / "suppression_rules.json"
    _write_config(config_path)
    monkeypatch.setenv("SUPPRESSION_CONFIG_PATH", str(config_path))
    clear_suppression_config_cache()

    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    state = create_initial_state(
        goal="custom suppression",
        scope={"systems": ["api"], "time_range": {}, "filters": {}},
        request_id="req-custom-suppression",
    )
    state["evidence"]["normalized_logs"] = [
        {
            "timestamp": "2026-06-24T00:00:00",
            "system": "api",
            "level": "WARN",
            "message": "custom noisy dependency",
            "stack_trace": "",
        }
    ]

    result = LogAnalysisAgent().run(state)

    assert result["evidence"]["known_pattern_matches"][0]["pattern_id"] == "KP-CUSTOM-NOISY-001"
    assert result["evidence"]["known_pattern_matches"][0]["match_result"] == "known_suppressed"
    assert len(result["evidence"]["suppressed_logs"]) == 1

    clear_suppression_config_cache()


def test_anomaly_detection_uses_configured_suppressed_key_fields(tmp_path, monkeypatch):
    config_path = tmp_path / "suppression_rules.json"
    _write_config(config_path)
    monkeypatch.setenv("SUPPRESSION_CONFIG_PATH", str(config_path))
    clear_suppression_config_cache()

    state = create_initial_state(
        goal="configured key fields",
        scope={"systems": ["api"], "time_range": {}, "filters": {}},
        request_id="req-configured-keys",
    )
    state["evidence"]["normalized_logs"] = [
        {"timestamp": "new", "system": "api", "level": "ERROR", "message": "same message"}
    ]
    state["evidence"]["suppressed_logs"] = [
        {"timestamp": "old", "system": "api", "message": "same message"}
    ]

    result = AnomalyDetectionAgent().run(state)

    assert result["metrics"]["anomaly_score"] == 0.0
    assert not result["evidence"]["anomalies"]

    clear_suppression_config_cache()


def test_impact_evaluation_uses_configured_suppression_credit(tmp_path, monkeypatch):
    config_path = tmp_path / "suppression_rules.json"
    _write_config(config_path, credit_per_log=7, max_credit=10)
    monkeypatch.setenv("SUPPRESSION_CONFIG_PATH", str(config_path))
    clear_suppression_config_cache()

    fake = FakeMCPClient()
    monkeypatch.setattr("app.agents.impact_evaluation.get_mcp_client", lambda: fake)
    state = create_initial_state(
        goal="configured impact credit",
        scope={"systems": ["api"], "time_range": {}, "filters": {}},
        request_id="req-impact-credit",
    )
    state["evidence"]["normalized_logs"] = [{"level": "ERROR", "message": "boom"}]
    state["evidence"]["anomalies"] = [
        {"severity": "high", "message": "boom"},
    ]
    state["evidence"]["suppressed_logs"] = [{"message": "noise"}, {"message": "noise2"}]

    result = ImpactEvaluationAgent().run(state)

    assert result["assessment"]["risk_score"] == 15
    assert "suppression_credit=10" in result["assessment"]["rationale"]

    clear_suppression_config_cache()
