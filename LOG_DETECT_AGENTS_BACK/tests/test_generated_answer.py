from app.main import build_generated_answer


def test_build_generated_answer_uses_message_and_stacktrace() -> None:
    answer = build_generated_answer(
        recommendation={
            "cause": "Permission mapping is missing",
            "recommendation": "Check role mapping and retry authorization.",
            "confidence": "HIGH",
        },
        message="테스트3님 권한이 없습니다. WorkID=552f54af-69e5-4f23-8402-6e9252bdad95",
        stacktrace="AuthService.checkPermission:42",
        occurrence_count=3,
        log_level="WARN",
        risk_level="Medium",
        risk_score=45,
    )

    assert "테스트3님 권한이 없습니다." in answer
    assert "AuthService.checkPermission:42" in answer
    assert "Permission mapping is missing" in answer
    assert "Check role mapping and retry authorization." in answer
    assert "Medium (45)" in answer
