"""Stub LogCollectorAgent implementation."""

from datetime import datetime, timedelta

from app.state import SharedState


class LogCollectorAgent:
    """Collect and normalize logs as deterministic stub data."""

    name = "LogCollectorAgent"

    def run(self, state: SharedState) -> SharedState:
        systems = state["scope"]["systems"] or ["unknown-system"]
        high_risk = any(k in state["goal"].lower() for k in ["auth", "payment", "결제", "인증"])
        disable_stack = bool(state["scope"].get("filters", {}).get("disable_stack_traces", False))
        now = datetime.utcnow()
        logs: list[dict] = []
        stack_traces: list[str] = []

        for idx in range(20):
            level = "INFO"
            message = "heartbeat ok"
            if high_risk and idx % 3 == 0:
                level = "ERROR"
                message = "exception detected in auth/payment flow"
            elif idx % 7 == 0:
                level = "WARN"
                message = "retry triggered"

            log_item = {
                "timestamp": (now - timedelta(minutes=idx)).isoformat(),
                "system": systems[idx % len(systems)],
                "level": level,
                "message": message,
            }
            if level == "ERROR" and not disable_stack:
                trace = f"Traceback: {log_item['system']}.service.process -> PaymentAuthError[{idx}]"
                log_item["stack_trace"] = trace
                stack_traces.append(trace)

            logs.append(log_item)

        state["evidence"]["normalized_logs"] = logs
        state["evidence"]["stack_traces"] = stack_traces
        state["decisions"]["agents_run"].append(self.name)
        return state
