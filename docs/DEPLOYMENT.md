# Local Docker / CI / Railway 배포 준비 설계
최초 작성: 2026-09-28 · 개정: 2026-09-29 · 이번 단계에서는 배포하지 않음

## 1. Local Docker 우선 서비스
프로젝트 및 Compose 실행 기준은 D:\workspace\portfolio-manager다. Phase 1 개발·검증은 Local 환경에서 먼저 완료한다. 아래 서비스 표는 최종 Phase 1 설계다. STEP 2에서는 PostgreSQL/Redis만 Docker Compose로 제공하고 API/Worker/Beat는 터미널/IDE에서 직접 실행한다. Qdrant/Object Storage profile은 이번 단계에 추가하지 않는다.

| 서비스 | 역할 | 연결·영속성 |
|---|---|---|
| API | FastAPI + Jinja2 | PG/Redis, RAG 업로드 원문 저장소, D2 Secret 기반 Single Admin, 기본 loopback 접근 |
| Worker | Celery, 수집·분석·Telegram·선택적 RAG | PG/Redis 필수, 외부/선택 dependency는 기능 사용 시 연결, Broker secret은 여기만 |
| Scheduler | Celery Beat 단일 replica | Redis, due schedule enqueue; Broker key 없음 |
| PostgreSQL | 금융·문서 메타·작업 결과의 원장 | private networking, 백업 |
| Redis | Celery broker, 단기 cache | private, eviction 금지 권고, 결과 원장 아님 |
| Qdrant | chunk/vector | 선택 rag profile, 기본 RAG_ENABLED=false로 없어도 시작 가능 |
| 원문 저장소 | 업로드/공시 원문 | Object Storage interface 확정, 로컬 호환 서버는 선택 profile |

한 코드베이스/검증된 동일 commit 또는 image digest를 세 프로세스에서 사용한다. 금융 공급자 호출은 Worker에 집중하여 outbound IP·token 경쟁을 줄인다. API의 Tool 요청도 저장 데이터 조회 우선이며 수집 필요 시 작업을 생성한다.
Beat는 하나만 가동한다. Rolling deploy 중 중복 Beat 가능성을 인정하고 DB event key/lease로 보호한다. 외부 call이 진행되는 worker에는 graceful shutdown과 작업 timeout을 적용한다.
Redis queue는 ingest, analysis, notify, rag로 논리 분리한다. 초기에는 한 worker 프로세스의 큐 소비로 시작할 수 있으나 긴 embedding이 broker sync를 굶기면 동시성 제한 또는 별도 Worker 서비스로 분리한다.

## 2. Qdrant 운영 선택 — D3 Deferred
| 선택 | 장점 | 부담·제약 |
|---|---|---|
| Railway self-host + persistent volume | 같은 프로젝트·private 연결, 설정 통제 | 버전 업그레이드·snapshot·복원·스토리지 관리 직접 수행 |
| Qdrant Cloud | 관리형 운영, 관리 기능 이용 | 외부 TLS 연결·별도 비용·리전/백업 기능은 플랜별 확인 |

이전의 Cloud 우선 권고는 보류한다. 현재는 Local Docker 선택 profile로 Qdrant adapter/계약을 검증하고 운영 환경의 Cloud/self-host 선택은 Railway 배포 검토 때 다시 결정한다. 어떤 선택도 로컬 비RAG 개발의 선행 조건이 아니다. 무료 tier의 백업·고가용성을 가정하지 않는다. [Qdrant Cloud 공식 문서](https://qdrant.tech/documentation/cloud/)
self-host 선택 시 ephemeral filesystem에 저장하지 않는다. snapshot을 같은 volume에만 두지 않고 독립 저장소로 복사한다. PG 메타 및 원문과 함께 실제 복원 훈련을 한다.

## 3. outbound IP와 비밀
D3는 Deferred다. Railway Hobby/Pro/Static Outbound IP는 로컬 완료 후 배포 시점의 실제 요건·가격으로 재검토한다. 토스 계정의 실제 허용 IP 요건을 검증하기 전 '고정 IP 불필요' 또는 '지금 Pro 구매 필수'로 단정하지 않는다. Static Outbound IP가 필수로 확인되면 실연동 활성화 전에 인프라 정책을 결정한다. [Railway 공식 출구 IP 문서](https://docs.railway.com/networking/static-outbound-ips)
로컬 fixture/test double 기반 BrokerProvider 개발은 이 결정을 기다리지 않는다. 로컬 실제 연동이 IP 조건 때문에 막히면 해당 실연동만 보류하고 나머지 기능은 계속 검증한다. 허용 IP 등록 우회나 비공식 Broker API를 사용하지 않는다.
APP_KEY/APP_SECRET, Toss client secret, LLM/News/DART/FRED key, notification credential, 암호화 key는 로컬 Docker secret 또는 Git에서 제외한 환경설정으로 주입하고 추후 Railway Secret으로 이동한다. PG에는 credential_ref와 masked label만 둔다.
access token은 짧은 수명 Worker memory가 기본. 필요 시 암호화된 Redis TTL cache와 분산 refresh lock을 쓰되 PG 평문 저장 금지. 한 프로세스 종료 후 재발급 정책과 provider quota를 검토한다.
API에 Broker secret을 주지 않는다. 로그는 Authorization·accountNo·CANO·cursor·개인 RAG 원문을 제거한다. CI에는 운영 Broker key를 주지 않는다.

## 4. CI와 배포 gate
PR 필수 check: ruff check/format check, mypy, pytest. 금융 도메인 단위 테스트, provider fixture 계약 테스트, PG/Redis 통합, RAG 비활성 부팅/분석 테스트와 Qdrant 선택 profile 통합 테스트를 구분한다. 기본 CI에는 Qdrant secret/서비스를 요구하지 않으며 RAG adapter 변경 시 선택 profile 검증도 수행한다. 테스트는 실제 주문 API 및 운영 계좌를 호출하지 않는다.
main 보호 규칙으로 필수 check 통과·최신 base 반영·PR review를 요구하고 관리자 bypass도 제한한다. main push의 최종 commit도 다시 검증한다.
로컬 단계에서 Railway deploy job/autodeploy는 활성화하지 않는다. 실제 Railway 배포를 결정한 뒤의 경로: GitHub Actions의 필수 CI job 모두 success → 명시적 deploy job → 해당 SHA의 이미지/소스만 Railway 배포. deploy job은 skipped/cancelled check를 통과로 간주하지 않는다. Railway의 별도 push autodeploy는 중복/선행 배포를 막기 위해 비활성화한다.
대안인 Railway Wait for CI는 push workflow를 전제로 하고 skipped/neutral/cancelled 처리에 예외가 있으므로 이것만으로 필수 gate를 구현하지 않는다. [공식 동작](https://docs.railway.com/deployments/github-autodeploys)
STEP 2에서 Alembic을 도입하며 Initial Migration은 Portfolio Foundation 11개 테이블만 Local PostgreSQL에서 검증한다. 배포 시에는 단일 migration runner + DB advisory lock, 사전 backup, expand/contract 호환 순서로 적용한다. API/Worker가 각각 동시에 migration을 실행하지 않는다. 실패하면 배포 중단.
배포 후 read-only smoke: health, DB 연결, 큐 처리, schema version, Admin 보호. 금융 API smoke는 별도 명시된 검증 절차에서 실행한다.

## 5. 실패와 운영
| 실패 | 반응 |
|---|---|
| Broker 401 | refresh 1회, 반복 시 인증 오류·운영 알림 |
| 429/5xx | retry-after 또는 지수 backoff+jitter, 제한된 재시도 |
| partial page / mapping 오류 | scope 잔고 publish 금지, 기존 snapshot 유지 |
| Redis 장애 | PG outbox pending 유지, 복구 후 dispatcher 재개 |
| Worker crash | lease 만료 및 PG 상태 기준 재처리 |
| LLM 장애 | budget 제한/DEGRADED, 수집은 계속 |
| RAG_DISABLED | 정상 비활성 상태, 비RAG 분석 계속; 오류 재시도/연결 시도 없음 |
| 활성 RAG 장애 | RAG_UNAVAILABLE/DEGRADED, 핵심 서비스 readiness 및 수집 계속 |
| 알림 응답 유실 | UNKNOWN, 중복 위험을 표시하고 D1 정책 적용 |
| queue 폭주 | 동일종목 후보 병합·오래된 시장 이벤트 만료, 공시 보존 |

Celery는 acks_late 등 설정만으로 exactly-once를 제공하지 않는다. DB unique 및 재처리 상태를 함께 사용한다. [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
운영 메트릭: sync 성공률/freshness, reconciliation mismatch, mapping unresolved, queue lag, event 수/중복률, LLM token/비용, tool timeout, outbox oldest age, 알림 실패, RAG READY/FAILED.
구조화 로그에는 request_id/sync_run_id/event_id/agent_run_id/outbox_id와 sanitized error만 포함한다. 외부 상용 trace 플랫폼은 필수가 아니다.

## 6. 보존·복구 제안
D7 저장 분리/최소 전송 방향은 확정이며 보존 기간은 잔여 R3이다. 기존 검토 후보일 뿐 운영 설정으로 자동 적용하지 않을 보존안: 금융·기초잔고·감사 이력은 사용자 삭제 전 유지, 분봉 90일/일봉 5년, 원문은 권리·사용자 삭제 정책에 따름, Agent 입출력 90일, 알림 1년, 민감 원문 로그 미저장.
Broker/domain 중복 키는 원본 행 존속 동안 유지한다. idempotency_request도 Phase 1 자동 만료를 적용하지 않고 최소 응답 참조를 유지한다. 향후 응답 축약 시 key/hash/resource tombstone을 보존한다. outbox 보존/삭제는 이 HTTP 기록과 독립이며 단순 TTL로 중복 금융 효과를 재생성하지 않는다.
목표 RPO 24시간/RTO 4시간은 권고치이며 선택 플랜으로 검증하기 전 SLA가 아니다. PG 일일 암호화 백업, 원문 백업, Qdrant snapshot 또는 원문 기반 재색인 경로를 시험한다.
롤백은 이전 호환 image로 수행하며 금융 데이터를 지우는 down migration을 자동 수행하지 않는다. schema가 호환되지 않으면 수정 배포를 선택한다. staging은 익명 fixture와 별도 secrets를 사용한다.

## 7. 로컬 profile·설정 계약
| 구성 | 기본값/범위 | 동작 |
|---|---|---|
| core | 직접 실행 API/Worker/Beat + Docker PG/Redis | Qdrant/Object Storage 미기동 상태에서 시작·핵심 흐름 검증 |
| RAG_ENABLED | false | DisabledKnowledgeProvider, 외부 embedding/색인 enqueue 없음 |
| rag profile | 명시 선택 | Qdrant와 Object Storage 호환 서버·격리 volume, 활성 adapter 통합 테스트 |
| DocumentStorage | provider interface | endpoint/bucket/region/credential 설정 분리; 원문 object key는 PG에 저장 |
| ADMIN_USER_ID | bootstrap된 UUID | ACTIVE app_user에 대응하는 서버측 Principal, 금융 DB 기본값 아님 |
| ADMIN_PASSWORD_HASH / SESSION_SECRET | 실제 값은 로컬 secret | Secret 인증·opaque Redis session; cookie/CSRF는 API_SPEC 기준 |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | 실제 값은 secret/config | 수신자 참조는 서버만 resolve, test double 우선 |
| LLM store | false | 외부 응답 저장 최소화, 일반 로그 body/프롬프트 제외 |
| 유료 Provider | 명시 설정 후 활성 | 미설정이면 typed UNAVAILABLE, 실호출은 R2 예산·권리 검토 뒤 |

기본 core의 depends_on/healthcheck/startup hook은 Qdrant/Object Storage를 요구하지 않는다. RAG=true여도 일시 장애가 API/Worker 전체 부팅을 막지 않게 lazy client를 사용한다. RAG 의존성은 별도 진단 항목이며 ready=true로 이를 숨기지 않는다.
PG/Redis 데이터는 Docker volume으로 유지하고 API/Worker filesystem을 공유 저장소로 취급하지 않는다. 비밀을 image layer·Compose 평문·Git history에 넣지 않는다. 실행 명령과 설정은 동일 repo의 README를 기준으로 한다.
부팅 시 app_user 행을 무조건 새로 생성하지 않는다. 초기 관리 절차가 한 번 발급한 UUID를 ADMIN_USER_ID로 참조하고 재시작 시 검증만 한다. DB가 없으면 마이그레이션/초기화가 필요함을 명확히 표시한다.

## 8. 단계별 검증 및 운영 전 gate
Phase 1 누적 로컬 검증 목표(기능별 후속 STEP 포함): Secret 인증 성공/실패·소유권 위반, 재시작 시 동일 app_user 유지, ABSOLUTE/DELTA CHECK, HTTP 동시 재요청/rollback/응답 유실, outbox 중복·큐 유실, RAG=false 무의존 부팅·검색·삭제 대기, 금지 sentinel의 LLM request 미노출.
선택 profile 검증: 원문 Object Storage 저장/복원, PG catalog/Qdrant index 정합성, RAG=true 장애 fallback, 비활성 후 잔여 작업 DEFERRED 및 재활성 resume.
실제 Telegram 발송 전 R1과 수신 설정, 유료 데이터/LLM 호출 전 R2, 실제 개인정보/원문 보관 전 R3를 점검한다. Railway 이전에는 D3를 재개한다. 이런 운영 gate는 fixture 기반 로컬 핵심 구현 착수를 막지 않는다.

## 9. STEP 2 실제 실행 구성 — 2026-10-05
- Python 3.12, pyproject.toml + requirements.lock. 명령은 루트 README 참고.
- Compose: loopback PostgreSQL/Redis + 영속 volume; 별도 test profile PostgreSQL은 5433 포트와 tmpfs 사용.
- 직접 실행: FastAPI, Celery Worker, 단일 Beat. Windows Celery solo는 개발용이며 공식 지원 환경은 Linux다.
- Beat schedule은 비어 있고 foundation.health만 제공한다. 향후 ingest/analysis/notify/rag 큐는 실제 기능 구현 시 도입한다.
- 로그인은 Argon2 hash + Redis session, 고정 TTL, CSRF/Origin, 기본 rate limit. HTTP는 명시적 loopback 개발에서만 허용하며 HTTPS origin에는 Secure cookie를 적용한다.
- RAG adapter는 DISABLED/UNAVAILABLE 인터페이스만 제공한다. 실제 Qdrant/Object Storage 연결은 없다.
- CI는 ruff/mypy/pytest, 실제 PostgreSQL Migration 및 Redis task 검증만 수행하며 Railway deploy job은 없다.
