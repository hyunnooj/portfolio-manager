# 의사결정 기록
최초 작성: 2026-09-28 · 개정: 2026-09-29 · 사용자 STEP 1 리뷰 반영
Source of Truth: D:\workspace\portfolio-manager/docs. 기존 저장소 외부 STEP 1 파일은 참고용이며 최신 기준이 아니다.
이 문서는 기존 D1–D7의 상태를 갱신한다. 확정된 방향을 다시 승인 요청하지 않는다. 이번 요청은 설계 문서 수정이며 STEP 2 실행·배포 승인은 포함하지 않는다.

## 결정 상태 요약
| 결정 | 상태 | 적용 결과 |
|---|---|---|
| D1 | Accepted — A | Telegram Bot 알림 + Admin 후속 질문 |
| D2 | Accepted — B | Secret 기반 Single Admin, app_user 기반 소유권; OAuth 미구현 |
| D3 | Deferred | Local Docker 우선; Railway 플랜/Static Outbound IP/운영 Qdrant는 배포 시점 검토 |
| D4 | Accepted — A | KR/US 현금 주식·ETF, 소수 수량, 현금/부채 제외 증권 평가 |
| D5 | Accepted — A | News/FXProvider 추상화·후보 검증·비용 통제; 실제 공급자/모델은 운영 전 선택 |
| D6 | Accepted — A | ORDER_AGGREGATE 명시·기초잔고·비교 가능한 재구성·INDETERMINATE |
| D7 | Accepted Direction — A | Object Storage 원문·PG metadata·Qdrant vector/chunk·외부 AI 최소 전송 |

## 이미 요구사항으로 확정
실제 주문 금지, 자동 Broker sync 우선, ticker와 내부 ID 분리, 계좌별 Position, 원통화 저장, UTC, 환경 Secret, 두 Agent, FastAPI/Jinja2, Celery/Redis/Beat, 8개 문서, DB 구현 전 설계 검토.
Qdrant 코드·인터페이스는 Phase 1에 포함하되 기본 RAG_ENABLED=false이며 application startup의 필수 dependency가 아니다. 운영 인프라 미선정과 기능 계약 미구현을 혼동하지 않는다.

## D1 — Accepted A: 알림 채널과 후속 대화
확정: Telegram Bot으로 알림을 보내고 Admin에서 후속 질문한다. 이메일 채널과 Telegram 답장 webhook은 현재 범위에 추가하지 않는다.
적용: NotificationProvider의 Telegram adapter, 사용자 설정 수신 chat 참조, sender 성공/실패/UNKNOWN 상태, 내부 Alert + outbox 유지. 응답 유실 UNKNOWN은 자동 재발송하지 않고 운영자 재시도만 허용하는 설계로 중복 위험을 노출한다.
남은 사항: 조용한 시간대·상한·운영 threshold는 R1이며 채널 선택 자체는 재검토 대상이 아니다.

## D2 — Accepted B: Single Admin 인증과 사용자 도메인
확정: Secret 기반 Single Admin 인증. Phase 1에서 signup/OAuth/SNS callback/일반 사용자 권한 시스템은 구현하지 않는다.
적용: 최소 app_user UUID, 개인 데이터의 user_id FK, 계좌 하위 데이터의 소유권 상속, Principal/UserContext 기반 Service 계약. ADMIN_USER_ID는 bootstrap된 사용자 참조일 뿐 금융 데이터의 default 상수가 아니다.
미래 Kakao/Naver/Google 로그인은 provider+subject를 별도 identity 연결표로 app_user.id에 연결할 수 있다. 지금은 해당 표/로그인 흐름을 만들지 않는다. Secret 회전이나 인증 공급자 변경으로 계좌/논지/알림 FK를 다시 쓰지 않는다.

## D3 — Deferred: Railway 및 Qdrant 운영
확정된 개발 방침: Phase 1을 D:\workspace\portfolio-manager의 Local Docker에서 우선 완료한다.
보류 범위: Railway Hobby/Pro, Static Outbound IP, 운영 Qdrant Cloud/self-host 선택과 인프라 비용.
재개 시점: Railway 배포 준비 또는 Toss 실제 API가 Static Outbound IP를 요구함이 확인된 시점. 로컬 test double/fixture 개발은 그 전에도 가능하다.
RAG_ENABLED=false로 Qdrant/Object Storage 미기동 상태에서 core 서비스가 부팅·분석해야 한다. 기능을 활성화할 때만 lazy 연결하며 활성 RAG 장애도 전체 startup을 막지 않는다.
이전 문서의 'Pro + Qdrant Cloud 우선 구매'로 읽힐 수 있는 권고는 현재 실행 전제에서 제거했다. 호스팅 비교는 미래 선택 자료로만 유지한다.

## D4 — Accepted A: 지원 자산과 평가 분모
KR/US 상장 현금 주식·ETF, KRW/USD, long 보유, decimal 소수 수량. 비중은 현금/예수금/부채를 제외한 보유 증권 평가액 기준이다.
전체 순자산 NAV, 신용·파생·채권 회계는 Phase 1 범위에 넣지 않는다. 미지원 항목과 평가 제외 사유는 화면에 표시한다.

## D5 — Accepted A: 데이터·모델 공급자 전략
NewsProvider/FXProvider 계약을 유지하고 KR/US coverage·저장/embedding 권리·품질 검증 뒤 공급자를 고른다. LLM 일일 token/비용 상한과 실행 제한을 둔다.
Marketaux 등은 후보이며 이번 A 확정이 특정 유료 상품·모델·예산의 확정을 의미하지 않는다. 실사용 공급자/model/embedding version과 한도는 R2에서 정한다. 비용 없는 fixture 기반 구현을 먼저 진행할 수 있다.

## D6 — Accepted A: 불완전 이력과 기초잔고
주문별 누적 체결을 ORDER_AGGREGATE로 명시하고 FILL과 배타적으로 계산한다. Broker 현재 Position이 기준이며 누락/기준 불일치/걸친 주문 baseline 미확인은 INDETERMINATE.
기초잔고와 일반 조정은 quantity_mode와 quantity로 구분한다. OPENING_BALANCE는 ABSOLUTE, TRANSFER/SPLIT_CORRECTION/OTHER는 DELTA이며 kind-mode CHECK로 모호한 조합을 금지한다.
과거 이력을 완전히 복원했다고 주장하지 않으며 개별 체결/세무손익 복원 제한을 유지한다.

## D7 — Accepted Direction A: 저장 경계와 외부 AI
원문은 Object Storage에 저장 가능한 DocumentStorage interface, metadata는 PostgreSQL, vector/chunk는 Qdrant로 관리한다. 로컬 호환 서버 또는 test double로 계약을 검증한다.
외부 LLM·embedding에 Broker 계좌번호/계좌 식별값/credential/token/주문·체결 ID/raw Broker response를 보내지 않는다. 합산 종목 exposure·비중·해석에 필요한 근거를 allowlist로 구성한다. 정확한 수량/절대금액은 기본 외부 입력에서 제외하고 서버가 최종 결과에 결합한다.
Responses store=false를 명시하고 외부 대화·파일 저장 및 일반 로그의 prompt/body 보관을 피한다. store=false를 모든 보존 제거/ZDR 활성화로 오해하지 않는다. 공식 정책 확인과 잔여 보존 선택은 AGENT_DESIGN/R3에 기록한다.

## 추가 리뷰 반영 모델
| 문제 | 이번 설계 | 이유 |
|---|---|---|
| 절대 기초수량과 증감의 혼용 | position_adjustment.quantity_mode + quantity | 컬럼명·kind-mode CHECK·API·계산식 모두 같은 의미 사용 |
| HTTP key와 queue 전달 혼용 | idempotency_request / outbox_message 분리 | HTTP 응답 replay와 async retry의 상태·수명 분리 |
| 고정 소유자 의존 | app_user UUID + user_id FK | 인증 공급자 변경 시 금융 소유권을 보존 |
| Qdrant startup 결합 | Disabled/QdrantKnowledgeProvider + lazy 연결 | 로컬 기본 실행과 선택 RAG 검증 분리 |
| 내부 snapshot 외부 노출 | 내부 input_snapshot / PrivacyFilter LLMContext 분리 | 내부 감사 가능성과 외부 최소 전송 동시 충족 |

이는 리뷰를 반영한 구현용 설계안이다. app_user/idempotency_request 추가로 DB는 26개 테이블이며 새로운 OAuth/RBAC 기능을 Phase 1에 도입하지 않는다.

## 남은 운영 Decision Required
아래 항목은 Local Docker/fixture 기반 STEP 2 착수의 blocker가 아니다. 실제 비용·전송·보관 기능 활성화 전에 결정한다. D1–D7의 확정 상태를 다시 미승인으로 돌리지 않는다.

### R1 — Decision Required: 실제 알림 운영값
문제: Telegram 선택은 확정됐으나 quiet hours/일일 상한/긴급 예외를 지정하지 않았다.
선택지 A: 조용한 시간대 없이 중요 이벤트를 중복 억제 후 전달.
장점: 중요 공시를 즉시 확인할 수 있다.
단점: 야간 알림 부담.
선택지 B: 조용한 시간대에 일반 알림을 지연, 긴급 규칙만 예외.
장점: 방해를 줄인다.
단점: 시차·긴급 분류 설정이 필요하다.
Recommended: A로 로컬 수신 검증 후 사용자 선호에 따라 시간대와 상한 지정.
Reason: threshold 등 값은 설정으로 바꿀 수 있어 DB/API를 막지 않는다. 실제 발송 전 선택한다.

### R2 — Decision Required: 실제 공급자·모델·예산
문제: 공급자 선정 전략은 확정됐으나 구독/모델/실사용 한도는 없다.
선택지 A: 후보 coverage·권리·비용·structured output 평가 후 선정.
장점: 근거 기반 선택과 교체 용이.
단점: 샘플 검증 시간이 필요.
선택지 B: 기존 보유 구독 중 계약을 충족하는 공급자부터 연결.
장점: 결제/권리 검토 재사용.
단점: 가용 데이터 범위에 제한.
Recommended: D5 A 전략 안에서 검증된 최소 공급자부터 시작.
Reason: 유료 사용 전에 뉴스/FX/model/embedding version, 일·월 예산을 고정하면 된다. 이번 작업에서 유료 호출/계약을 하지 않는다.

### R3 — Decision Required: Object Storage 운영 제공자와 보존 기간
문제: 저장 분리/최소 전송은 확정됐으나 실제 storage 리전·삭제/백업·내부 분석/원문 보존 기간은 미지정이다.
선택지 A: 선택한 Object Storage의 lifecycle·암호화·백업 정책으로 운영.
장점: 원문 수명과 복구 관리가 명확하다.
단점: 비용·리전·정책 검증 필요.
선택지 B: 로컬 호환 Object Storage와 수동 관리로 개발 검증만 수행하고 운영 선택 연기.
장점: 외부 개인정보 저장 없이 진행 가능.
단점: 운영 보존/복구 수준은 검증되지 않음.
Recommended: 로컬은 B, 실제 개인정보 운영 전 A와 보존 기간 결정.
Reason: 원문/내부 snapshot의 보존은 LLM API store=false와 독립이다. 최소 전송 정책은 이미 확정되었으며 더 많은 개인정보 전송을 승인 요청하는 항목이 아니다.

## 문서 정합성 검토 범위와 STEP 2
PHASE1_SPEC/ARCHITECTURE/DB_DESIGN/API_SPEC/AGENT_DESIGN/DEPLOYMENT/DECISIONS/ROADMAP 모두에 이번 변경 영향이 있다.
검토 항목: D3 Deferred, local-first, RAG 비활성/readiness, identity/FK/공용 문서, quantity mode, HTTP/queue 멱등성, 내부/외부 AI 문맥, Telegram 후속질문 경계, Phase 2 기능 제외.
2026-09-29 점검 결과: 8개 문서의 내부 링크·코드블록 경계, DB 26개 테이블/346개 컬럼의 사전 형식·FK 대상, 과거 owner_key/owner_scope/quantity_delta 잔존 여부, HTTP key와 outbox 필드 분리를 확인했다. 검토한 계약 간 모순은 발견되지 않았다. 업로드 재요청은 RAG flag보다 기존 완료 응답 replay를 우선하고, 신규 작업만 비활성 제한을 적용하도록 일치시켰다.
검증 범위는 문서와 Git 변경 확인이다. 실행 가능한 DB/앱/Docker 설정이 없으므로 런타임·마이그레이션·실 API 검증을 수행한 것으로 보고하지 않는다. 변경은 docs의 8개 Markdown 파일뿐이며 README와 Git 설정은 수정하지 않았다.
STEP 2의 로컬 기반 DB 모델/마이그레이션·도메인·Provider/Service·테스트 구현을 시작할 수 있는 설계 상태다. 운영 gate는 위 R1/R2/R3 및 D3를 각각 해당 활성화 시점에 적용한다. 2026-09-29 STEP 1 요청에서는 문서만 정리했다. 2026-10-05 STEP 2 요청으로 로컬 기반 구현을 진행하며 아래 단계별 제한을 적용한다.

## STEP 2 실행 범위 확정 — 2026-10-05
Initial Migration은 DB_DESIGN §1의 Portfolio Foundation 11개 테이블로 제한한다. 전체 26개 논리 설계는 축소하지 않는다.
DESIGN ISSUE STEP2-DB-01: 범위 밖 broker_order 때문에 trade_execution.order_id 컬럼/FK도 주문 기능의 후속 Migration까지 함께 보류한다.
API/Worker/Beat는 Local 터미널/IDE에서 직접 실행하고 Compose는 PG/Redis 중심이다. Beat의 실제 업무 스케줄, Provider/Agent/RAG/Telegram, OAuth/RBAC, Railway는 선행 구현하지 않는다.
Single Admin은 ADMIN_PASSWORD_HASH와 SESSION_SECRET을 환경설정에서 읽으며 Redis opaque session으로 ADMIN_USER_ID를 ACTIVE app_user에 매핑한다.
D1–D7 및 R1/R2/R3, D3 Deferred 상태는 변경하지 않는다. 이 범위 결정은 ROADMAP 기능을 Phase 1에 추가하지 않는다.
