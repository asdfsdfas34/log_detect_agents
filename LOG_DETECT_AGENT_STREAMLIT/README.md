# LogDetect Streamlit Frontend

Vue 기반 대시보드 기능을 Streamlit으로 이관한 프론트엔드입니다.

## 포함 기능

- 서비스 목록 조회 및 서비스 선택
- 분석 실행(`POST /analyze`) + ChromaDB 저장 옵션
- 실행 상태(Status/Stage/Last run) 표시
- 요약 지표 카드(Total logs, Anomalies, Unique patterns, Impact score, Risk, System health)
- Impact 시각화(진행률 + 막대 차트)
- Pattern Cluster 테이블
- Anomaly Timeline 라인 차트
- Source Code Analysis 섹션
- Recommendation / Verification Steps 표시 및 다운로드
- Agent Execution Timeline

## 실행 방법

```bash
cd LOG_DETECT_AGENT_STREAMLIT
pip install -r requirements.txt
streamlit run app.py
```

## 환경 변수

- `API_BASE_URL` (기본값: `http://localhost:8000`)

백엔드 API 스펙(`/health`, `/services`, `/analyze`)은 기존 Vue 프론트엔드와 동일하게 사용합니다.
