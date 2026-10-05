# API 및 Admin 계약
최초 작성: 2026-09-28 · 개정: 2026-09-29 · 설계용 계약 · 외부 API 호출/구현 없음

## 1. 공통 규칙
prefix /api/v1. JSON UTF-8. 모든 내부 ID는 UUID이며 예시의 K1/A1 같은 이름은 읽기 편한 별칭이다. 금액·수량·환율은 decimal string, 시각은 RFC3339 UTC Z, 날짜는 YYYY-MM-DD, 통화는 ISO 4217이다.
D2 B 확정: Secret 기반 Single Admin 인증으로 생성한 Principal.user_id를 사용한다. 이는 app_user.id UUID이며 클라이언트가 소유자를 지정할 수 없다. single user라도 보호 없는 공개 Admin/API는 허용하지 않는다.
리스트는 items, next_cursor, has_more, as_of를 반환한다. limit 기본 50/최대 200, (정렬시각,id) 기반 opaque cursor. 특정 snapshot을 넘어갈 때 next_cursor에 snapshot ID를 포함한다.
오류: error={code,message,request_id,details,retryable}. 비밀·raw provider 응답은 details에 넣지 않는다. HTTP 400 문법, 401/403 운영자 접근 실패, 404 없음, 409 중복/버전 충돌, 422 금융 의미 검증, 429 제한, 503 dependency 실패.
stale 정보는 200 + quality=STALE/PARTIAL로 제공할 수 있다. 데이터 자체가 없으면 null + reason으로 반환하며 0으로 가장하지 않는다.

## 2. 조회 및 작업 API
| Method / Path | 입력 | 응답·상태 | Service / 주요 테이블 |
|---|---|---|---|
| GET /health/live | 없음 | 200 프로세스 생존 | 외부 호출 없음 |
| GET /health/ready | 없음 | 200/503 DB·Redis 준비, rag 상태 부가정보 | Qdrant/Object Storage는 필수 준비조건 아님 |
| GET /brokers | 없음 | 연결 capability·상태·last_success | BrokerService/account/sync |
| GET /accounts | cursor | masked label·source_mode·범위 | broker_account |
| GET /accounts/{id}/positions | scope | native 수량·평단·as_of·quality | account_position |
| GET /portfolio | valuation_at? | 종목 합산·계좌 breakdown·KRW평가·누락 | PortfolioService |
| GET /executions | account_id?,instrument_id?,from?,to?,cursor | 단위 FILL/ORDER_AGGREGATE와 coverage | trade_execution |
| GET /orders | account_id?,status?,cursor | 읽기 전용 주문 이력 | broker_order |
| POST /accounts/{id}/sync | scopes[], Idempotency-Key | 202 sync_run_ids[] | BrokerSyncService |
| GET /sync-runs/{id} | 없음 | 상태·scope·coverage·오류코드 | sync_run |
| GET /reconciliations | account_id?,status?,cursor | 계산/관측/차이·판정근거 | reconciliation_result |
| POST /reconciliations/{id}/resolve | action,reason,evidence | 200 처리 메모 | 기존 금융 수량 수정 안 함 |
| POST /manual-transactions | 아래 계약, Idempotency-Key | 201 거래 | trade_execution |
| POST /manual-transactions/{id}/void | reason, expected_version | 200 취소 표기 | 삭제 대신 감사 이력 |
| POST /opening-balances | 아래 계약, Idempotency-Key | 201 기초잔고 | position_adjustment |
| POST /position-adjustments | quantity_mode=DELTA,quantity,reason,evidence | 201 승인된 수량조정 | position_adjustment |
| POST /position-adjustments/{id}/void | reason, Idempotency-Key | 200 무효화 및 재대사 요청 | 기초잔고 포함, 원본 행 유지 |
| GET /events | type?,instrument_id?,cursor | 규칙·근거·상태 | event |
| GET /events/{id} | 없음 | 이벤트와 분석 이력 | event,agent_run |
| POST /events/{id}/analyses | reason,Idempotency-Key | 202 agent_run_id | 재분석, 알림 자동 재전송 안 함 |
| GET /agent-runs/{id} | 없음 | 단계·결과·근거·실패 | agent_run |
| GET /alerts | state?,cursor | 알림 및 전송 상태 | alert |
| GET /alerts/{id} | 없음 | 분석·근거·당시 snapshot·대화 | alert,agent_run,conversation_message |
| POST /alerts/{id}/retry-delivery | reason,Idempotency-Key | 202/409 | 실패/UNKNOWN 처리 정책 적용 |
| POST /alerts/{id}/questions | text,Idempotency-Key | 202 question_id,agent_run_id | 기존 두 Agent 재사용 |
| GET /alerts/{id}/messages | cursor | user/assistant/status | conversation_message |
| GET /theses | instrument_id? | 최신 및 버전 목록 | investment_thesis |
| POST /theses | instrument_id,text,expected_version | 201 신규 버전 | 기존 버전 immutable |
| GET /rag-documents | instrument_id?,state?,cursor | 메타·처리상태·오류 | rag_document |
| POST /rag-documents | multipart file + metadata | 활성 202 document_id / 비활성 409 RAG_DISABLED | 원문 Object Storage + metadata PG |
| POST /rag-documents/{id}/reindex | Idempotency-Key | 활성 202 / 비활성 409 RAG_DISABLED | 동일 버전 point upsert |
| DELETE /rag-documents/{id} | expected_version | 202 DELETING | 비활성에서도 tombstone; 외부 삭제는 복구 후 수행 |
| GET /instruments | query,market? | 검증된 식별 후보 | instrument |

POST는 운영 데이터 기록/작업 요청이며 Broker 주문을 뜻하지 않는다. 주문 실행·취소 endpoint는 존재하지 않는다. 투자 논지 자동 변경·새 계좌에 비밀 입력 UI는 포함하지 않는다.

## 3. 멱등성과 동시성
업무 변경 요청은 Idempotency-Key 필수. idempotency_request의 (user_id, operation, idempotency_key) unique를 사용한다. operation은 API 버전+HTTP method+route template이며 canonical request hash에는 path의 실제 대상 ID·검증된 body·효과에 영향을 주는 query를 포함한다. multipart는 파일 내용 hash와 metadata를 사용하고 secret/session/CSRF 값은 hash 대상에서 제외한다.
인증·소유권·순수 입력 검증 후 같은 PG transaction에서 요청 예약, 업무 행 변경, 필요한 outbox 생성, 응답 기록을 commit한다. IN_PROGRESS 예약만 먼저 commit하지 않는다. 동일 요청 동시 실행은 unique/row lock으로 직렬화하고 제한된 lock wait 초과 시 409 REQUEST_IN_PROGRESS + Retry-After를 반환한다. 업무 transaction이 rollback되면 요청 예약도 없어져 같은 key로 다시 처리할 수 있다.
같은 key·같은 hash는 최초 HTTP status/body/Location을 재생하며, 다른 hash는 409 IDEMPOTENCY_CONFLICT다. 업무 변경 성공 응답은 resource_type/resource_id(여러 개면 resource_ids)/location만 포함하는 최소 DTO로 통일한다. 원래 202였으면 작업 완료 뒤에도 재요청은 같은 202와 resource ID를 반환하고 현재 상태는 GET으로 확인한다. 작업 실패 재실행은 명시적 endpoint와 새 key를 사용한다.
Phase 1에는 요청 key를 자동 만료시키지 않는다. 응답 보존을 나중에 줄이더라도 key/hash/resource 참조 tombstone은 유지하여 오래된 재요청이 새 금융 효과를 만들지 않게 한다. key가 없어도 Broker 이력은 별도의 domain unique로 보호한다.
outbox_message는 HTTP key/hash/응답을 저장하지 않는다. domain event_key와 payload만 비동기 전달한다. Scheduler 작업은 idempotency_request 없이 outbox를 생성할 수 있다. 계좌 sync는 별도로 scope별 실행 lease와 기존 실행 ID를 사용한다.
폼 중복 클릭 방지용 key와 CSRF token은 별개다. 쿠키는 secure/HttpOnly/SameSite, origin 검사와 CSRF 검증을 적용한다. 접근 자격은 로컬 Docker secret/미추적 환경설정에 주입하고 추후 Railway Secret으로 옮긴다. 문서·Git에 실제 값을 쓰지 않는다.

## 4. 금융 입력 계약
manual-transactions: account_id, instrument_id, side(BUY/SELL), quantity>0, price>=0, currency, executed_at(명시 offset), fee?, tax?, note, external_reference?, expected_version?를 받는다.
BROKER_API 계좌에는 수동 거래가 잔고를 직접 바꾸지 않는다. 기본은 MANUAL 계좌에만 허용. Broker 이력 누락 보정이 필요하면 D6에 따른 명시적 correction으로 처리하고 중복 반입 방지 기준을 기록한다.
opening-balances: account_id,instrument_id,quantity_mode=ABSOLUTE,quantity>=0,unit_cost?(null 허용),currency,effective_at,boundary_basis,reason,evidence. endpoint가 kind=OPENING_BALANCE를 정하며 다른 mode는 422 QUANTITY_MODE_MISMATCH. 동일 계좌·종목·effective_at의 활성 OPENING은 하나이고 이 시점까지 포함된 거래는 합산 제외한다.
position-adjustments: account_id,instrument_id,effective_at,quantity_mode=DELTA,quantity(signed nonzero),kind(TRANSFER/SPLIT_CORRECTION/OTHER),currency,boundary_basis,reason,evidence. ABSOLUTE 및 OPENING_BALANCE 입력은 이 endpoint에서 422로 거절한다. 체결로 위장하지 않으며 자동 기업행위 기능이 아니다.
예: 기초 10은 {kind:OPENING_BALANCE,quantity_mode:ABSOLUTE,quantity:"10"}; 2주 입고는 {kind:TRANSFER,quantity_mode:DELTA,quantity:"2"}; 1주 출고는 quantity:"-1". 잔고 계산은 10+2-1=11이며 기초잔고를 일반 delta처럼 더하지 않는다.
expected_version 불일치 시 409. Broker row에 수동 void 요청은 422. 동일 체결을 수동과 API 양쪽으로 입력하면 자동 합산하지 않고 격리한다.

## 5. 대표 Portfolio 응답 예
아래 가격·환율·수량은 설명용 가상 값이다.
```json
{
  "base_currency": "KRW",
  "valuation_at": "2026-09-28T12:00:00Z",
  "valuation_scope": "SECURITIES_ONLY",
  "quality": "COMPLETE",
  "positions": [{
    "instrument_id": "00000000-0000-4000-8000-000000000001",
    "symbol": "AAPL",
    "quantity": "15",
    "currency": "USD",
    "price": "200",
    "price_as_of": "2026-09-28T12:00:00Z",
    "fx_to_krw": "1350",
    "fx_as_of": "2026-09-28T12:00:00Z",
    "market_value_native": "3000",
    "market_value_krw": "4050000",
    "accounts": [{"label":"KIS","quantity":"5"},{"label":"TOSS","quantity":"10"}]
  }],
  "total_market_value_krw": "4050000",
  "excluded": [],
  "warnings": []
}
```
이 응답은 인증된 Admin의 운영 조회 DTO다. accounts[]를 포함한 API 응답을 LLM 프롬프트에 그대로 직렬화하지 않는다. Agent Tool은 별도 합산 ExposureContext만 반환한다. broker label은 표시용이다. 완전 평가가 불가능하면 total_market_value_krw=null, known_subtotal_krw를 별도 반환하며 missing_price/missing_fx/unsupported_assets/stale_accounts를 나열한다. 과거 valuation_at은 저장 데이터로 당시 잔고를 증명할 수 있을 때만 지원하고 그렇지 않으면 422 HISTORICAL_POSITION_UNAVAILABLE을 반환한다. 현재 수량을 과거 수량으로 사용하지 않는다.

## 6. 업로드·검색
파일은 PDF/TXT/MD, 상한 20MiB, 텍스트 중심 문서를 초기 제안으로 한다. 외부 임의 URL 다운로드는 SSRF 위험을 제어하기 위해 공개 입력으로 제공하지 않는다. Provider가 허용한 공식 도메인은 내부 수집할 수 있다.
RAG metadata는 instrument_ids[], document_type,title,source,published_at?,fiscal_year?,quarter?,language이다. 수동 업로드는 source=USER. 동일 내용 hash와 metadata scope는 기존 ID를 반환한다. 원문은 DocumentStorage interface를 통한 Object Storage에 저장하며 처리 절차는 AGENT_DESIGN을 참조한다. 사용자 업로드는 visibility=PRIVATE, user_id=Principal.user_id로 서버가 지정한다. 공개 기업 문서 등록은 신뢰된 내부 수집 경로만 허용한다.

## 7. Single Admin 인증과 미래 identity
인증 화면은 /admin/login, 제출 POST /admin/login, 종료 POST /admin/logout으로 한정한다. signup/OAuth callback/provider 연결 API는 Phase 1에 없다. 로그인/로그아웃은 업무 Idempotency-Key 대상이 아니며 CSRF/Origin 보호와 로그인 rate limit을 적용한다.
Secret 검증 후 서버측 Redis session(opaque cookie, 제한 TTL)에 user_id를 매핑한다. 별도 SQL session/user-role 테이블을 만들지 않는다. 인증 secret과 session signing secret은 데이터베이스에 저장하지 않는다. secret 회전 시 인증 epoch를 변경해 기존 session을 무효화할 수 있게 한다.
ADMIN_USER_ID가 기존 ACTIVE app_user에 대응하지 않으면 접근을 허용하지 않는다. 금융 API는 언제나 해당 사용자의 계좌/대상 소유권을 검사하며 다른 사용자 객체는 404로 처리한다. 문서상 다중 identity를 수용하더라도 실제 동시 Multi User 로그인은 Phase 2다.
기본 로컬 환경도 인증을 생략하지 않는다. 기본 검증은 로컬 TLS와 Secure cookie를 사용하며, 명시적인 loopback 개발 설정에서만 비Secure cookie를 허용하고 외부 bind에서는 거부한다. 가입/비밀번호 재설정 시스템은 추가하지 않는다.

## 8. RAG 비활성 계약
RAG_ENABLED=false의 readiness는 PG/Redis 상태로 판단하고 rag={enabled:false,status:DISABLED}를 표시한다. true지만 연결 불가인 경우 rag.status=UNAVAILABLE을 표시하되 핵심 readiness는 계속 사용 가능하다. 모니터링은 RAG 장애를 별도 경고한다.
목록 조회는 PG metadata를 보여주며 ready 문서라도 검색 기능 상태를 DISABLED로 표시한다. 신규 업로드/재색인은 body의 원문 저장 및 idempotency 예약 전에 409 RAG_DISABLED를 반환하며 Qdrant/embedding/Object Storage를 호출하지 않는다. 다만 인증·소유권·hash가 확인된 기존 COMPLETED 요청의 재전송은 기능 flag보다 응답 replay를 우선한다. 이는 새 RAG 작업이나 외부 호출을 만들지 않는다.
삭제는 비활성에서도 PG tombstone과 삭제 outbox를 commit하여 즉시 검색에서 제외한다. 물리 삭제는 의존성 사용 가능 시 완료하며 202는 물리 삭제 완료를 뜻하지 않는다. 비활성 기간의 대기 작업은 attempt를 소진하지 않고 deferred 처리한다.
Thesis 저장은 RAG와 무관하게 성공한다. 비활성 중에는 RAG 문서·색인 작업을 만들지 않으며 활성화 후 운영자가 backfill을 명시적으로 요청한다.

업로드의 Object Storage 쓰기는 긴 DB transaction 밖에서 content hash 기반 임시 object key로 수행한다. 이미 완료된 Idempotency-Key 요청은 먼저 응답을 재생하여 재업로드를 생략한다. 동시 요청이 같은 원문을 저장해도 object put은 동일 key/content로 멱등 처리하고, PG transaction의 U24/U20 승자만 문서·색인 작업을 확정한다. DB 실패의 고아 object는 grace period 후 metadata 대조로 정리한다. 외부 저장 성공만으로 202를 반환하지 않는다.
