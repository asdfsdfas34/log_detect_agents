"""Insert deterministic demo rows into service_logs_v2."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db.scenario_store import ensure_schema
from app.db.sqlite_store import _resolve_db_path


DEMO_EVENTS = [
    {
        "event_id": "evt_demo_sqlserver_connection_timeout",
        "template_id": "dependency_timeout",
        "canonical_event_id": "sqlserver_timeout",
        "template_text": "connection to <*> timed out after <DURATION>",
        "service": "test_appl",
        "dependency": "sqlserver",
        "severity": "ERROR",
        "entity_type": "dependency",
        "entity_id": "sqlserver",
        "error_code": "ETIMEDOUT",
        "parameter_values": {"duration_ms": 30000},
        "raw_message": "SQL Server connection timed out after 30000ms",
    },
    {
        "event_id": "evt_demo_sqlserver_login_failed",
        "template_id": "dependency_auth_failed",
        "canonical_event_id": "sqlserver_login_failed",
        "template_text": "login failed for user <*>",
        "service": "test_appl",
        "dependency": "sqlserver",
        "severity": "ERROR",
        "entity_type": "dependency",
        "entity_id": "sqlserver",
        "error_code": "SQL_LOGIN_FAILED",
        "parameter_values": {"retry_count": 3},
        "raw_message": "SqlException: Login failed for user appadmin2",
    },
    {
        "event_id": "evt_demo_msmq_mail_queue_missing",
        "template_id": "dependency_unavailable",
        "canonical_event_id": "msmq_mail_queue_unavailable",
        "template_text": "<*> queue service is not installed on this computer",
        "service": "test_appl",
        "dependency": "msmq",
        "severity": "ERROR",
        "entity_type": "dependency",
        "entity_id": "mail_queue",
        "error_code": "QUEUE_SERVICE_NOT_INSTALLED",
        "parameter_values": {"queue_depth": 0},
        "raw_message": "SendNotification-MAIL message queue service is not installed",
    },
    {
        "event_id": "evt_demo_approval_line_user_missing",
        "template_id": "entity_missing",
        "canonical_event_id": "approval_line_user_missing",
        "template_text": "approval line user <*> does not exist",
        "service": "test_appl",
        "dependency": "",
        "severity": "ERROR",
        "entity_type": "approval_line",
        "entity_id": "line_user",
        "error_code": "APPROVAL_USER_NOT_FOUND",
        "parameter_values": {"missing_user_count": 1},
        "raw_message": "결재선(Line)의 사용자 정보가 존재하지 않습니다.",
    },
    {
        "event_id": "evt_demo_approval_status_if_failed",
        "template_id": "external_interface_failed",
        "canonical_event_id": "approval_status_if_failed",
        "template_text": "approval status interface failed for ApvID <*>",
        "service": "test_appl",
        "dependency": "approval_if",
        "severity": "ERROR",
        "entity_type": "workflow",
        "entity_id": "approval_status",
        "error_code": "APPROVAL_IF_FAILED",
        "parameter_values": {"retry_count": 5},
        "raw_message": "결재 상태 전송 실패 ApvID 12345 / lineInfo.approvalIFStatus",
    },
    {
        "event_id": "evt_demo_ai_agent_type_error",
        "template_id": "application_type_error",
        "canonical_event_id": "ai_agent_line_userid_type_error",
        "template_text": "cannot read property <*> of undefined",
        "service": "test_appl",
        "dependency": "",
        "severity": "ERROR",
        "entity_type": "script",
        "entity_id": "callAIAgentAPI",
        "error_code": "TYPEERROR",
        "parameter_values": {"line_no": 72},
        "raw_message": "TypeError: Cannot read property lineUserID of undefined at callAIAgentAPI",
    },
    {
        "event_id": "evt_demo_webrequest_http_404",
        "template_id": "dependency_http_error",
        "canonical_event_id": "external_http_404",
        "template_text": "remote server returned HTTP <*>",
        "service": "test_appl",
        "dependency": "external_http",
        "severity": "ERROR",
        "entity_type": "endpoint",
        "entity_id": "notification_feed",
        "error_code": "HTTP_404",
        "parameter_values": {"status_code": 404},
        "raw_message": "SendNotification-FEED 원격 서버에서 (404) 찾을 수 없음 오류를 반환했습니다.",
    },
    {
        "event_id": "evt_demo_batch_function_convert_error",
        "template_id": "parameter_conversion_failed",
        "canonical_event_id": "sap_parameter_numeric_conversion_failed",
        "template_text": "cannot convert String into NUM(<*>)",
        "service": "test_appl",
        "dependency": "sap",
        "severity": "ERROR",
        "entity_type": "function_parameter",
        "entity_id": "I_SPERNR_TO",
        "error_code": "NUM_CONVERSION_FAILED",
        "parameter_values": {"target_precision": 8},
        "raw_message": "PARAMETER I_SPERNR_TO of FUNCTION TEST_INT_ENTRUST_LIST cannot convert String into NUM(8)",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Insert deterministic service_logs_v2 demo rows."
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing evt_demo_* rows before inserting.",
    )
    args = parser.parse_args()

    db_path = Path(_resolve_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        if args.replace:
            cur.execute("DELETE FROM service_logs_v2 WHERE event_id LIKE 'evt_demo_%'")
        rows = []
        for index, event in enumerate(DEMO_EVENTS):
            created_at = (now - timedelta(minutes=index * 5)).isoformat(
                timespec="seconds"
            )
            rows.append(
                (
                    event["event_id"],
                    event["template_id"],
                    event["canonical_event_id"],
                    event["template_text"],
                    event["service"],
                    event["dependency"],
                    event["severity"],
                    event["entity_type"],
                    event["entity_id"],
                    event["error_code"],
                    json.dumps(
                        event["parameter_values"],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    None,
                    event["raw_message"],
                    created_at,
                )
            )
        cur.executemany(
            """
            INSERT INTO service_logs_v2(
                event_id,
                template_id,
                canonical_event_id,
                template_text,
                service,
                dependency,
                severity,
                entity_type,
                entity_id,
                error_code,
                parameter_values,
                source_log_id,
                raw_message,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(event_id) DO UPDATE SET
                template_id=excluded.template_id,
                canonical_event_id=excluded.canonical_event_id,
                template_text=excluded.template_text,
                service=excluded.service,
                dependency=excluded.dependency,
                severity=excluded.severity,
                entity_type=excluded.entity_type,
                entity_id=excluded.entity_id,
                error_code=excluded.error_code,
                parameter_values=excluded.parameter_values,
                raw_message=excluded.raw_message,
                created_at=excluded.created_at,
                updated_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        conn.commit()

    action = "Replaced" if args.replace else "Upserted"
    print(f"{action} {len(DEMO_EVENTS)} demo service_logs_v2 rows in {db_path}")


if __name__ == "__main__":
    main()
