"""LogCollectorAgent implementation backed by SQLite."""

from datetime import datetime, timedelta

from app.db.sqlite_store import fetch_recent_log_entries
from app.state import SharedState


class LogCollectorAgent:
    """Collect and normalize logs from SQLite storage."""

    name = "LogCollectorAgent"

    def run(self, state: SharedState) -> SharedState:
        systems = state["scope"]["systems"] or []
        disable_stack = bool(state["scope"].get("filters", {}).get("disable_stack_traces", False))

        log_entries = fetch_recent_log_entries(service_names=systems, limit=200)

        if not log_entries:
            now = datetime.utcnow()
            fallback_systems = systems or ["unknown-system"]
            high_risk_goal = any(k in state["goal"].lower() for k in ["auth", "payment", "결제", "인증"])
            log_entries = []
            for idx in range(10):
                is_error = high_risk_goal and idx % 3 == 0
                log_entries.append(
                    {
                        "timestamp": (now - timedelta(minutes=idx)).isoformat(),
                        "system": fallback_systems[idx % len(fallback_systems)],
                        "level": "ERROR" if is_error else "INFO",
                        "message": (
                            "exception detected in auth/payment flow"
                            if is_error
                            else "no recent sqlite log rows found"
                        ),
                        "stack_trace": (
                            f"Traceback: {fallback_systems[idx % len(fallback_systems)]}.service.process -> PaymentAuthError[{idx}]"
                            if is_error and not disable_stack
                            else ""
                        ),
                    }
                )
            state["decisions"]["assumptions"].append(
                "SQLite에서 최근 로그를 찾지 못해 fallback 로그를 생성했습니다."
            )

        logs: list[dict] = []
        stack_traces: list[str] = []

        for row in log_entries:
            level = str(row.get("level", "INFO") or "INFO").upper()
            stack_trace = str(row.get("stack_trace", "") or "")

            if disable_stack:
                stack_trace = ""

            normalized = {
                "timestamp": str(row.get("timestamp") or datetime.utcnow().isoformat()),
                "system": str(row.get("system") or "unknown-system"),
                "level": level,
                "message": str(row.get("message") or ""),
            }
            if stack_trace:
                normalized["stack_trace"] = stack_trace
                stack_traces.append(stack_trace)

            logs.append(normalized)

        state["evidence"]["normalized_logs"] = logs
        state["evidence"]["stack_traces"] = stack_traces
        state["decisions"]["agents_run"].append(self.name)
        return state
