from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class AgentState(TypedDict, total=False):
    messages: List[Message]
    service_name: Optional[str]
    raw_logs: List[str]
    collected_logs: str
    log_analysis: str
    impact_evaluation: str
    source_code_analysis: str
    recommendation: str
    next: Literal[
        "log_collector",
        "log_analysis",
        "impact_evaluation",
        "source_code_analysis",
        "recommendation",
        "end",
    ]
    metadata: Dict[str, str]
