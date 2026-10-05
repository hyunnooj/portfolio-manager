# Phase 2 이후 Roadmap
최초 작성: 2026-09-28 · 개정: 2026-09-29
이 문서의 기능은 Phase 1 구현에 자동 편입하지 않는다. 실제 주문 기능은 현재 장기 계획에도 자동 승인된 것이 아니다.

| 후보 | 도입 계기 | 선행 조건·영향 |
|---|---|---|
| MCP Server | 외부 Agent/클라이언트가 동일 Tool 사용 | 기존 Service 위 adapter, 도구 인증·scope |
| Redis Streams | 작업 이외 소비자별 replay 필요 | 소비자 group·보존·중복 모델, outbox 호환 |
| Temporal | 장시간 human approval·workflow 복구가 커짐 | Celery/LangGraph 경계 재설계·운영비 검토 |
| Kafka | 다수 사용자·고빈도 event fan-out | 실제 처리량 근거·partition/ordering 설계 |
| Multi User / SNS 로그인 | 사용자 2명 이상 또는 Kakao/Naver/Google 로그인 도입 | Phase 1 app_user UUID/FK 유지; external_identity(provider,subject,user_id) 추가·account linking·tenant 권한 검증·필요 시 RLS/secret vault |
| React/Next.js | 풍부한 대시보드·대화 UX 필요 | 기존 API 유지, 별도 프런트 운영 |
| Additional Broker | 추가 계좌 수요 | Provider capability 및 identity/수량 기준 계약 테스트 |
| CSV import | 미지원 Broker/역사 복원 수요 | import_batch·row provenance·manual/API 중복 해소 |
| 자동 기업행위 | split·합병·배당·대체입출고 빈번 | corporate_action/ledger·source revision·원가 재계산 |
| 현금·부채 포함 NAV | 실제 전체 계좌 자산 평가 | account_cash·settlement·FX 회계 정의 |
| Thesis change 고도화 | 장기 논지 변화 추적 | 사용자 버전과 AI 제안 분리, 승인된 변경만 반영 |
| Agent 추가 분리 | 두 Agent의 역할 병목이 측정됨 | eval로 효과 확인, 비용·workflow 증가 검토 |
| OTel/Agent 관측 고도화 | 분산 trace/운영 분석 요구 | 개인정보 필터·sampling·외부 보존 정책 |
| 모바일 앱/Push | 채널 중심 알림 한계 | 디바이스 토큰·동의·OS별 전달 정책 |
| 실시간 WebSocket | 분 단위 polling으로 부족 | reconnect/gap fill/sequence·시장 데이터 사용권 |
| 무제한 대화·메신저 답장 | 후속 질문 사용량 증가 | 대화 retention·webhook 검증·context 비용 |

## 진입 기준
Phase 1의 자동 잔고 동기화·멱등성·정합성·근거 정확성·알림 중복 방지·복원 절차를 먼저 검증한다. 이후 실제 지연·비용·오류·사용 빈도를 근거로 하나씩 선택한다.
MCP/Temporal/Kafka를 채택하기 위해 현재 DB를 불필요하게 일반화하지 않는다. 현재 Provider/Service/Tool 분리와 outbox가 확장의 출발점이다.

## 이번 리뷰 이후 경계
app_user와 user_id FK는 Phase 1의 최소 소유권 모델이며 SNS 로그인 구현을 뜻하지 않는다. OAuth callback/가입/계정 연결/역할 관리/다중 사용자 운영은 이 Roadmap에 남긴다.
Local Docker 우선과 RAG_ENABLED=false는 Phase 1의 개발·실행 방식 변경이다. Qdrant/DocumentStorage adapter 계약은 Phase 1에 포함하며 Railway Hobby/Pro/Static Outbound IP 및 운영 Qdrant 선택만 배포 시점으로 보류한다. 이를 MCP/Temporal/Kafka 등 다른 Roadmap 기능의 도입 근거로 삼지 않는다.
