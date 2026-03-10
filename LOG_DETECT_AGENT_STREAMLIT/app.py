from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from api_client import BackendClient

STEP_NAMES = [
    "OrchestratorAgent",
    "LogCollectorAgent",
    "LogAnalysisAgent",
    "AnomalyDetectionAgent",
    "IncidentCorrelationAgent",
    "ImpactEvaluationAgent",
    "SourceCodeAnalysisAgent",
    "KnowledgeBaseRAGAgent",
    "RecommendationAgent",
]


st.set_page_config(page_title="LogDetect Dashboard", layout="wide")


def init_state() -> None:
    defaults: dict[str, Any] = {
        "execution_status": "idle",
        "current_stage": "Not started",
        "last_execution_at": None,
        "health_status": "unknown",
        "health_model": "unknown",
        "stub_mode": "unknown",
        "loading": False,
        "error": None,
        "service_options": [],
        "selected_service": "",
        "save_to_chromadb": False,
        "result_state": None,
        "timeline": [{"name": step, "status": "pending"} for step in STEP_NAMES],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def show_toast(message: str, icon: str = "✅") -> None:
    try:
        st.toast(message, icon=icon)
    except Exception:
        # st.toast may not be available in old versions.
        st.info(message)


def fetch_health(client: BackendClient) -> None:
    payload = client.health()
    st.session_state.health_status = payload.get("status", "unknown")
    st.session_state.health_model = payload.get("model", "unknown")
    st.session_state.stub_mode = payload.get("stub_mode", "unknown")


def fetch_services(client: BackendClient) -> None:
    try:
        st.session_state.service_options = client.services()
    except Exception as exc:  # noqa: BLE001
        st.session_state.service_options = []
        show_toast(f"서비스 목록을 불러오지 못했습니다: {exc}", icon="❌")


def update_timeline(result: dict[str, Any]) -> None:
    decisions = result.get("decisions", {})
    run = set(decisions.get("agents_run", []))
    skipped = set(decisions.get("skipped_agents", []))
    failed = {item.get("node") for item in decisions.get("failures", [])}

    timeline = []
    for step in STEP_NAMES:
        if step in failed:
            status = "failed"
        elif step in run:
            status = "completed"
        elif step in skipped:
            status = "skipped"
        else:
            status = "pending"
        timeline.append({"name": step, "status": status})

    st.session_state.timeline = timeline
    pending = next((item for item in timeline if item["status"] == "pending"), None)
    st.session_state.current_stage = pending["name"] if pending else "Completed"


def run_analysis(client: BackendClient) -> None:
    service_name = st.session_state.selected_service.strip()
    if not service_name:
        show_toast("서비스를 먼저 선택해주세요.", icon="⚠️")
        return

    st.session_state.loading = True
    st.session_state.execution_status = "running"
    st.session_state.error = None
    st.session_state.current_stage = "Starting execution"
    st.session_state.timeline = [
        {"name": step, "status": "running" if i == 0 else "pending"}
        for i, step in enumerate(STEP_NAMES)
    ]

    try:
        payload = client.analyze(service_name, st.session_state.save_to_chromadb)
        result = payload.get("result", {})
        st.session_state.result_state = result
        update_timeline(result)
        failures = result.get("decisions", {}).get("failures", [])
        st.session_state.execution_status = "failed" if failures else "completed"
        st.session_state.last_execution_at = datetime.now().isoformat(timespec="seconds")
        fetch_health(client)
        show_toast("분석이 완료되었습니다.")
    except Exception as exc:  # noqa: BLE001
        st.session_state.execution_status = "failed"
        st.session_state.error = str(exc)
        show_toast(f"Analysis failed: {exc}", icon="❌")
    finally:
        st.session_state.loading = False


def metric_overview(result: dict[str, Any]) -> dict[str, Any]:
    evidence = result.get("evidence", {})
    assessment = result.get("assessment", {})
    risk_score = assessment.get("risk_score") or 0
    if risk_score >= 70:
        risk = "High"
    elif risk_score >= 30:
        risk = "Medium"
    else:
        risk = "Low"
    return {
        "total_logs": len(evidence.get("normalized_logs", [])),
        "total_anomalies": len(evidence.get("anomalies", [])),
        "unique_patterns": len(evidence.get("clusters", [])),
        "impact_score": risk_score,
        "risk": risk,
    }


def render_header_controls(client: BackendClient) -> None:
    c1, c2, c3, c4, c5 = st.columns([1.0, 2.0, 2.2, 1.3, 1.2])

    if c1.button("서비스 새로고침"):
        fetch_services(client)

    options = st.session_state.service_options or [""]
    idx = options.index(st.session_state.selected_service) if st.session_state.selected_service in options else 0
    st.session_state.selected_service = c2.selectbox("서비스 선택", options=options, index=idx)

    with c3:
        st.caption(f"Status: **{st.session_state.execution_status}**")
        st.caption(f"Stage: **{st.session_state.current_stage}**")
        st.caption(f"Last run: {st.session_state.last_execution_at or '-'}")

    c4.toggle("ChromaDB 저장", key="save_to_chromadb")
    c5.button(
        "Re-run analysis",
        type="primary",
        disabled=st.session_state.loading or not st.session_state.selected_service.strip(),
        on_click=run_analysis,
        args=(client,),
    )


def render_overview(result: dict[str, Any]) -> None:
    overview = metric_overview(result)
    cols = st.columns(6)
    cols[0].metric("Total logs", overview["total_logs"])
    cols[1].metric("Anomalies", overview["total_anomalies"])
    cols[2].metric("Unique patterns", overview["unique_patterns"])
    cols[3].metric("Impact score", overview["impact_score"])
    cols[4].metric("Risk", overview["risk"])
    cols[5].metric("System health", st.session_state.health_status, st.session_state.health_model)


def render_visuals(result: dict[str, Any]) -> None:
    metrics = result.get("metrics", {})
    evidence = result.get("evidence", {})

    impact_df = pd.DataFrame(
        {
            "Metric": ["Frequency", "Timing", "Traffic"],
            "Value": [
                round((metrics.get("error_rate") or 0) * 100),
                min(100, round((metrics.get("latency_p95") or 0) / 3)),
                max(0, min(100, round(metrics.get("rps") or 0))),
            ],
        }
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Impact Score")
        st.progress(min(100, int(metric_overview(result)["impact_score"])) / 100)
        st.write(f"**{metric_overview(result)['impact_score']} / 100**")
    with col2:
        st.subheader("Impact Metrics")
        st.bar_chart(impact_df, x="Metric", y="Value")

    st.subheader("Pattern Clusters")
    clusters = sorted(evidence.get("clusters", []), key=lambda item: item.get("count", 0), reverse=True)
    total = sum(item.get("count", 0) for item in clusters) or 1
    cluster_df = pd.DataFrame(
        [
            {
                "Cluster": item.get("cluster", ""),
                "Count": item.get("count", 0),
                "Similarity(%)": round((item.get("count", 0) / total) * 100),
            }
            for item in clusters
        ]
    )
    st.dataframe(cluster_df, use_container_width=True)

    st.subheader("Anomaly Timeline")
    logs = [log for log in evidence.get("normalized_logs", []) if log.get("timestamp")]
    anomalies = evidence.get("anomalies", [])
    timeline_rows = []
    for log in logs:
        count = len([a for a in anomalies if a.get("system") == log.get("system")])
        timeline_rows.append({"timestamp": log.get("timestamp"), "anomaly_count": count})
    if timeline_rows:
        timeline_df = pd.DataFrame(timeline_rows)
        st.line_chart(timeline_df, x="timestamp", y="anomaly_count")
    else:
        st.info("시계열 데이터가 없습니다.")


def render_source_and_recommendation(result: dict[str, Any]) -> None:
    evidence = result.get("evidence", {})
    final = result.get("final", {})

    with st.expander("Source Code Analysis", expanded=True):
        traces = evidence.get("stack_traces", [])
        if not traces:
            st.write("No stack traces")
        for trace in traces:
            st.code(trace)
            st.caption("File path: app/services/payment_auth_*.py")
            st.caption("Module: app.services")
            st.caption("Function: process_request")

    st.subheader("Recommendations")
    generated_answer = final.get("generated_answer")
    if generated_answer:
        st.info(generated_answer)

    for item in final.get("recommended_actions", []) or []:
        st.markdown(
            f"- **{item.get('priority', 'N/A')}** | {item.get('action', '')}  \\n  Owner: `{item.get('owner', '')}`"
        )

    verification_steps = final.get("verification_steps", []) or []
    verification_text = "\n".join(verification_steps)
    st.code(verification_text or "No verification steps")
    st.download_button(
        "검증 절차 텍스트 다운로드",
        data=verification_text.encode("utf-8"),
        file_name="verification_steps.txt",
        mime="text/plain",
        disabled=not bool(verification_text),
    )


def render_timeline() -> None:
    st.subheader("Agent Execution Timeline")
    df = pd.DataFrame(st.session_state.timeline)
    st.dataframe(df, use_container_width=True)


def main() -> None:
    init_state()
    client = BackendClient.from_env()

    st.title("LogDetect Dashboard (Streamlit)")
    st.caption("Enterprise Monitoring")

    top1, top2 = st.columns([1, 1])
    if top1.button("Health check"):
        try:
            fetch_health(client)
            show_toast("Health 상태를 갱신했습니다.")
        except Exception as exc:  # noqa: BLE001
            show_toast(f"Health check 실패: {exc}", icon="❌")
    if top2.button("서비스 목록 조회"):
        fetch_services(client)

    if not st.session_state.service_options:
        fetch_services(client)
    try:
        fetch_health(client)
    except Exception:
        pass

    render_header_controls(client)

    if st.session_state.loading:
        st.info("Running multi-agent analysis")

    if st.session_state.error:
        st.error(st.session_state.error)

    result = st.session_state.result_state
    if result:
        render_overview(result)
        render_visuals(result)
        render_source_and_recommendation(result)
        render_timeline()
    elif not st.session_state.loading:
        st.warning("No analysis result yet. Trigger a run to populate the dashboard.")


if __name__ == "__main__":
    main()
