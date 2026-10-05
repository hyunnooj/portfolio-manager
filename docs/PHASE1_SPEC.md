# Phase 1 요구사항 명세
최초 작성: 2026-09-28 · STEP 1 개정: 2026-09-29 · STEP 2 범위 반영: 2026-10-05
이 문서는 현재 개발할 범위만 정의한다. D1/D2/D4/D5/D6는 확정, D7은 A 방향 확정, D3 인프라 선택은 Deferred다. 운영 세부 미결정과 개발 착수 조건은 [DECISIONS](DECISIONS.md)를 따른다.

## 1. 현재 저장소 분석과 산출물
Source of Truth는 `D:\workspace\portfolio-manager`이며 이후 STEP 2도 동일 저장소에서 진행한다. 개정 시작 시 저장소에는 .git과 README.md만 있고 기존 코드·docs·의존성·배포 설정은 없었으며 working tree는 깨끗했다. 저장소와 확인 가능한 상위 경로에 AGENTS.md는 없었다.
기존 STEP 1 산출물을 참고하여 이번 결정과 모델 수정을 반영한 최신 문서 8개를 저장소 docs/에 정리한다. 저장소 외부 산출물은 참고용이며 프로젝트 기준이나 동기화 대상이 아니다.
이번 작업은 문서 작성이다. 애플리케이션·DDL·SQLAlchemy 모델·마이그레이션·프런트엔드·배포 파일을 만들거나 실제 계좌/시세/LLM API를 호출하지 않는다. 공식 문서와 공개 OpenAPI 명세만 읽었다.

## 2. 목표와 사용자 흐름
단일 사용자의 KIS·Toss 계좌를 자동 동기화하고 보유 종목의 가격·거래량·공시·뉴스·거시 지표 이벤트를 감지한다. Python 규칙이 후보를 만들고 Research Agent와 Portfolio Analyst Agent가 근거 및 포트폴리오 영향을 분석한다. 정책 엔진이 알림을 결정하고 Telegram Bot으로 전달한다. 알림 상세에서 후속 질문을 이어간다.
Admin의 최근 Alert 목록만으로는 앱을 열지 않아도 알게 된다는 목표를 충족하지 못한다. D1 확정에 따라 외부 알림은 Telegram Bot, 후속 질문은 Admin으로 제공한다.

## 3. 필수 범위
| 영역 | Phase 1 계약 | 완료 기준 |
|---|---|---|
| 사용자 | Secret 기반 Single Admin 인증, app_user UUID에 데이터 소유권 연결 | Principal.user_id로 조회 격리, 가입·OAuth·RBAC 구현 없음 |
| Broker | KIS/Toss 공식 조회 API, 계좌별 자동 동기화·수동 재실행 | 실패 시 기존 정상 잔고 유지, 상태/최종 성공시간 표시 |
| Portfolio | instrument와 계좌 Position 분리, 종목 합산, KRW 평가 | KIS AAPL 5 + Toss AAPL 10 = 15 |
| 거래 | 조회 가능한 주문·체결 History, 반복 동기화 멱등성, 정합성 비교 | 중복 없음, 누락/집계 이력은 명시 |
| Fallback | MANUAL 거래와 OPENING_BALANCE, 수동 계좌 경로 | Broker 잔고와 수동 잔고 이중 합산 방지 |
| 데이터 | KIS 우선 시세, OpenDART/SEC 공시·재무, FRED, 교체 가능한 NewsProvider | source·기준시각·수집시각·품질 표시 |
| 이벤트 | 6종 규칙을 버전 관리 YAML로 관리 | LLM 없이 후보 생성·중복 억제 |
| Agent | Research + Portfolio Analyst 2개, Function Tool, Structured Output | 출처 검증·실패 및 비용 제한 |
| RAG | Object Storage 원문·PostgreSQL 메타데이터·Qdrant chunk/vector 인터페이스 | 기본 RAG_ENABLED=false, Qdrant 없이 startup/분석 성공; 활성 profile에서 종목 필터·장애 fallback 검증 |
| Thesis | 사용자 논지·메모 등록 및 버전 기록 | 논지가 없으면 이를 명시하고 분석 지속 |
| UI | FastAPI + Jinja2 Admin와 알림별 후속 질문 | 별도 프런트 프로젝트 없이 운영 확인 |
| 작업 | Redis + Celery Worker + Beat | 재시도·멱등성·재처리·단일 scheduler |
| 배포 | Local Docker 우선, CI 유지, Railway는 후속 배포 검토 | pytest/ruff/mypy 통과와 로컬 완료 우선; Hobby/Pro/출구 IP는 D3 Deferred |

## 4. 데이터 지원 경계
D4 A 확정: KR/US 상장 현금 주식·ETF, KRW/USD, long 보유이며 소수 수량은 decimal로 수용한다. 평가 분모는 현금·부채를 제외한 보유 증권 가치다. 미지원 상품을 조용히 버리지 않고 미지원 목록과 평가 제외 이유를 노출한다.
Broker API가 조회하지 못하는 주문·역사적 체결을 복원했다고 주장하지 않는다. Toss 주문 조회의 유형 제한과 주문별 누적 체결은 [ARCHITECTURE](ARCHITECTURE.md)에 기록한다. 체결 전체 복원은 자동 연동 완료 조건과 별개다.
현재 Position은 Broker 응답 기준이다. 실행 이력으로 재구성한 수량은 별도 검증값이며 잔고를 덮어쓰지 않는다. 장중 체결·결제 기준이 맞지 않으면 불일치 확정 대신 비교 불가로 표시한다.

## 5. Admin 및 후속 대화
/admin에서 연결 상태, 계좌별 잔고, 통합 Portfolio, 거래·주문 History, 동기화 요청과 진행, 정합성 결과, Manual 거래·기초잔고, RAG 목록·설정 상태(활성 시 업로드), Thesis, Event·Alert·실패 상태를 제공한다.
알림 상세의 간단한 질문 입력 → 기존 두 Agent workflow 재사용 → 근거 있는 응답 저장. 독립 챗봇 제품, 무제한 대화 기억, 별도 세 번째 Agent는 포함하지 않는다. 알림 당시 데이터와 최신 데이터를 명확하게 구분한다.

## 6. 검증 시나리오와 잠정 운영 목표
필수 검증은 DB_DESIGN의 5개 예시 외에 부분 페이지 실패, 완전한 빈 잔고, 소수점 체결, 누적 체결 변경, 지연 응답, 미국 DST, RAG 장애, LLM 잘못된 출처, 알림 전송 후 응답 유실을 포함한다.
잠정 설정값: 장중 시세 1분, Broker 5분, 뉴스/공시 5분, 거시 30분. 거래소 휴장·공급자 지연·quota에 따라 달라지며 실시간 보장이나 확정 SLA가 아니다. 이벤트 검출 이후 정상 부하에서 3분 내 분석·전달을 목표로 계측한다.
운영 화면은 freshness, queue lag, 누락 종목, 마지막 정상 동기화, 재처리 대상을 보여야 한다. 장애 시 stale 데이터를 최신으로 표시하지 않는다.

## 7. 현재 제외
실제 주문·매수·매도·정정·취소, OAuth 사용자 로그인, 다중 사용자, CSV importer, 자동 기업행위 완전 처리, 세금·실현손익 회계, 모바일 Push, React, MCP 서버, Kafka/Streams/Temporal은 현재 구현 대상이 아니다. 향후 항목은 [ROADMAP](ROADMAP.md).
OAuth client credentials를 이용한 Broker 토큰 발급은 사용자 OAuth 로그인과 다른 외부 API 인증 절차다.

## 8. 요구사항 추적
| 원 요청 | 주 설계 문서 |
|---|---|
| 1–4 목표·사용자·Broker·추상화 | 본 문서, ARCHITECTURE |
| 5–11 종목·DB·거래·멱등성·통화·보안·시간 | DB_DESIGN |
| 12–16 공급자·이벤트·Agent·Tool·RAG | ARCHITECTURE, AGENT_DESIGN |
| 17–21 Admin·작업·인프라·CI·스택 | API_SPEC, DEPLOYMENT |
| 22–24 상세 DB·5개 사례·설계만 작성 | DB_DESIGN |
| 25–30 문서 분리·Roadmap·결정·보고 | 전체 8문서, DECISIONS, ROADMAP |

## 9. 읽는 순서
[Architecture](ARCHITECTURE.md) → [DB 설계](DB_DESIGN.md) → [API](API_SPEC.md) → [Agent](AGENT_DESIGN.md) → [배포](DEPLOYMENT.md) → [결정](DECISIONS.md) → [Roadmap](ROADMAP.md).

## 10. 개정된 구현 준비 기준
- 인증과 소유권을 분리한다. app_user 1개를 초기화하되 수량 1개 제한이나 'primary' 소유자 상수를 금융 Domain에 넣지 않는다. OAuth identity 연결과 다중 사용자 서비스는 ROADMAP에 유지한다.
- 기초잔고는 quantity_mode=ABSOLUTE, 일반 조정은 DELTA로 기록한다. HTTP 재요청은 idempotency_request, 비동기 전달은 outbox_message가 각각 담당한다.
- STEP 2 Local 기본 구성은 터미널/IDE의 API·Worker·Beat와 Docker Compose의 PostgreSQL·Redis다. Initial Migration은 DB_DESIGN의 STEP 2 목록 11개로 제한한다. Qdrant/Object Storage와 실제 기능은 해당 후속 STEP에서 검증한다.
- RAG_ENABLED=false에서 검색은 RAG_DISABLED를 반환하고 embedding/Qdrant 호출·색인 작업을 생성하지 않는다. 금지된 RAG 변경 API와 이미 존재하는 작업의 처리 계약은 API/AGENT 문서를 따른다.
- 외부 LLM에는 allowlist 기반 종목별 합산 exposure·비중·필요한 근거만 전달한다. 계좌번호·credential·token·주문/체결 ID·raw Broker response는 금지한다.
- STEP 2 로컬 구현 착수에 필요한 설계는 준비되었다. 실제 유료 호출·실계좌 연동·외부 발송·Railway 배포는 각 운영 준비 조건을 충족해야 한다. STEP 1 당시에는 문서 수정만 수행했으며 2026-10-05 STEP 2 요청으로 로컬 기반 구현이 승인되었다.
