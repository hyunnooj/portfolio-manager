# portfolio-manager

개인 투자자를 위한 Proactive Investment AI Agent의 **STEP 2 Local Development Foundation**입니다.
FastAPI/Jinja2, SQLAlchemy, PostgreSQL, Redis/Celery를 사용하는 Modular Monolith입니다.
실제 Broker 조회·주문·Agent·Telegram·RAG 저장/검색은 아직 구현하지 않았습니다.
프로젝트 기준 경로는 `D:\workspace\portfolio-manager`입니다.

## 구현 범위

```text
app/
  auth/             Redis opaque session, 비밀번호 검증, rate limit
  core/             환경설정, DB 연결
  models/           Portfolio Foundation 11개 모델, 정확한 수치/UTC 타입
  repositories/     Position 조회, HTTP 멱등 기록, Outbox
  services/         트랜잭션 멱등성, Outbox 전달 경계, RAG 상태 인터페이스
  jobs/             Celery health task, 비어 있는 Beat schedule
  templates/        로그인 및 Admin
  main.py           FastAPI application factory
alembic/versions/   독립된 Migration 이력
scripts/           로컬 설정 및 Admin identity 초기화
tests/             unit/API/PostgreSQL/Redis queue 테스트
docs/              Phase 1 전체 설계 (이번 STEP보다 넓은 범위)
.github/workflows/ CI 검사, 배포 없음
```

## 환경 준비 — Windows PowerShell

Python **3.12.x**, Docker Desktop의 Linux container engine, Git이 필요합니다.
의존성 기준은 `pyproject.toml`이며, 검증한 전이 의존성 버전은 `requirements.lock`에 고정합니다.
Python 3.12.14에서 설치 및 검증했습니다. 다른 Python minor는 이번 단계 검증 범위가 아닙니다.
인프라는 PostgreSQL 17.11 / Redis 7.4.11-alpine으로 고정했습니다.
[PostgreSQL 릴리스](https://www.postgresql.org/docs/release/17.11/)와
[Redis 릴리스](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisce-7.4-release-notes/) 및 공식 이미지 태그를 확인했습니다.

```powershell
Set-Location D:\workspace\portfolio-manager
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e '.[dev]'
.\.venv\Scripts\python.exe -m scripts.setup_local
.\.venv\Scripts\python.exe -m scripts.configure_admin
```

기존 `.venv`가 정상이라면 재생성할 필요가 없습니다. `py`가 Python을 찾지 못하면 Python 3.12를
설치하거나 설치된 `python.exe`의 전체 경로로 첫 명령을 실행하세요.
가상환경 activate 없이도 위처럼 전체 실행 경로를 사용할 수 있습니다.
Linux/WSL에서는 `python3.12 -m venv .venv`, 이후 `.venv/bin/python`을 사용합니다.

`setup_local`은 `.env.example`을 바탕으로 임의의 로컬 DB 비밀번호를 생성하고 기존 `.env`는
덮어쓰지 않습니다. `configure_admin`은 비밀번호를 화면에 표시하지 않고 입력받아 Argon2 해시,
사용자 UUID, 세션 비밀을 `.env`에 저장합니다. 다시 실행하면 사용자 UUID는 보존하고 기존
세션은 무효화합니다. 이 파일을 공유하거나 Git에 추가하지 마세요.

## 인프라와 DB 생성

Docker Desktop을 실행하고 engine이 준비된 뒤 실행합니다.

```powershell
docker compose up -d --wait postgres redis
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.bootstrap_admin
.\.venv\Scripts\python.exe -m alembic current
```

Compose는 **PostgreSQL과 Redis 인프라**를 제공합니다. API/Worker/Beat는 별도 터미널 또는
IDE에서 직접 실행합니다. 컨테이너 포트는 loopback에만 공개하며 PG/Redis는 named volume으로
보존됩니다. 앱 startup에서는 테이블 생성, Migration, Admin 생성 또는 외부 API 호출을 하지 않습니다.
`bootstrap_admin`은 환경설정의 UUID를 가진 ACTIVE identity를 한 번 생성하며 재실행해도 중복되지 않습니다.
DISABLED 사용자를 임의로 복구하지 않습니다.

Initial Migration: `alembic/versions/0001_portfolio_foundation.py`.
업무 테이블 **11개** + Alembic 내부 이력 테이블 `alembic_version` 1개가 생성됩니다.
DB 제약에 `btree_gist` extension을 사용하므로 Migration 계정은 extension 생성 권한이 필요합니다.
Local Compose 계정은 이를 지원합니다. Migration과 별도 DDL 파일을 이중 관리하지 않습니다.

```powershell
docker compose exec postgres psql -U portfolio -d portfolio -c '\dt'
```

## API 및 Admin 실행

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

- <http://127.0.0.1:8000/health/live>: 프로세스 생존 확인.
- <http://127.0.0.1:8000/health/ready>: PG/Redis 연결 상태, 선택적 RAG 상태. 인프라 실패 시 503.
- <http://127.0.0.1:8000/admin/login>: 설정한 관리자 비밀번호로 로그인.
- <http://127.0.0.1:8000/admin>: 인증 확인 및 POST 로그아웃.

Readiness의 PG 검사 `SELECT 1`은 연결 검사이며 Schema 최신 여부를 대신하지 않습니다.
실행 전에 `alembic upgrade head`를 별도로 수행해야 합니다.
`RAG_ENABLED=false`이면 Qdrant 없이 시작하며 `DISABLED`를 반환합니다.
현재 true 설정도 adapter 미구현이므로 `UNAVAILABLE`이며 핵심 readiness를 막지 않습니다.
RAG HTTP 업무 endpoint는 아직 제공하지 않습니다.

로컬 HTTP는 loopback 접속에 한해 명시적으로 허용합니다. `PUBLIC_ORIGIN`과 브라우저 주소를
정확히 일치시키세요(`localhost`와 `127.0.0.1`은 서로 다른 origin).
외부 환경은 HTTPS가 필수이며 HTTPS origin이면 Secure cookie가 자동 적용됩니다.
HttpOnly/SameSite=Strict, Redis TTL 1시간, Origin/CSRF 검사, IP별 분당 5회 및 전체 30회 로그인 제한을
사용합니다. 세션 TTL은 갱신 없는 절대 만료입니다. `AUTH_EPOCH` 변경 또는 `SESSION_SECRET` 회전으로
기존 세션을 무효화합니다. 실제 요청마다 ACTIVE `app_user`를 확인합니다.
Reverse proxy 도입 전에는 신뢰할 proxy/forwarded-header 정책을 별도 검토하세요.

## Worker / Beat — 각각 별도 터미널

Windows 로컬 검증용:

```powershell
Set-Location D:\workspace\portfolio-manager
.\.venv\Scripts\python.exe -m celery -A app.jobs.celery_app:celery_app worker --pool=solo --loglevel=INFO
```

Celery는 Windows를 공식 지원하지 않습니다. 위 solo 실행은 로컬 개발용이며, 지원되는 실행 환경은
Linux/WSL입니다. Linux에서는 `.venv/bin/python -m celery -A app.jobs.celery_app:celery_app worker --loglevel=INFO`를 사용합니다.
[Celery 공식 FAQ](https://docs.celeryq.dev/en/stable/faq.html#does-celery-support-windows).

```powershell
# 별도 터미널: Beat는 한 개만 실행
.\.venv\Scripts\python.exe -m celery -A app.jobs.celery_app:celery_app beat --loglevel=INFO
# 다른 터미널: Redis → Worker → 결과 확인
.\.venv\Scripts\python.exe -c "from app.jobs.celery_app import health_task; print(health_task.delay().get(timeout=15))"
```

기본 큐는 `foundation`, Beat schedule은 비어 있습니다. Health task는 수동 호출만 하며 실제 수집·분석·알림 스케줄을 등록하지 않습니다.
Outbox Publisher는 주입 가능한 전달 경계만 제공하며 주기 실행이나 업무 Consumer는 후속 단계입니다.
PUBLISHED는 Broker 접수 상태이고 Consumer 처리가 끝난 DONE과 다릅니다. 전달은 at-least-once이므로
Consumer는 event_key로 중복을 처리해야 합니다. 장기 재시도/DEAD 정책은 실제 전달 기능 단계에서 추가합니다.

## 테스트 및 CI

DB 없이 수행하는 검사:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q -m 'not integration and not queue'
```

실제 PostgreSQL/Redis까지 검사:

```powershell
docker compose --profile test up -d --wait postgres-test redis
$env:TEST_REDIS_URL = 'redis://127.0.0.1:6379/15'
.\.venv\Scripts\python.exe -m pytest -q
```

`TEST_DATABASE_URL`은 `.env`에서 로드합니다. 개발 DB 5432와 테스트 DB 5433을 분리합니다.
테스트는 이름이 `_test`로 끝나는 PostgreSQL DB만 허용하고 임의 schema 안에 Migration을 적용한 뒤
그 schema만 제거합니다. 테스트용 PG container는 tmpfs로, 재생성하면 데이터가 사라집니다.
Queue 테스트는 고유 큐와 Redis DB 15를 사용하며 테스트가 직접 solo worker를 실행합니다.
`TEST_DATABASE_URL`/`TEST_REDIS_URL`이 없으면 해당 integration/queue 검사는 **skip**됩니다.
CI에서는 두 값을 모두 제공하므로 생략하지 않습니다. Broker/LLM Secret은 필요 없습니다.

검증 내용: 빈 DB Migration 및 downgrade/upgrade, 모델 drift, FK/unique/check, 유효기간 중복,
KIS AAPL 5 + Toss AAPL 10 = 15, 사용자 격리, UTC/Decimal, 멱등 replay/충돌/동시성/rollback,
Outbox lease/fencing, 로그인/CSRF/만료/장애, 실제 Redis task 전달.

## 환경변수

| 변수 | 용도 |
|---|---|
| APP_ENV | local / test / production |
| POSTGRES_PASSWORD | 로컬 Compose DB 비밀번호 |
| DATABASE_URL | SQLAlchemy psycopg 연결 URL |
| TEST_DATABASE_URL | 별도 `*_test` 데이터베이스 |
| REDIS_URL | 세션/Celery broker/backend |
| TEST_REDIS_URL | 테스트 전용 Redis DB |
| ADMIN_USER_ID | 초기화된 ACTIVE app_user UUID |
| ADMIN_PASSWORD_HASH | Argon2 비밀번호 해시 (평문 저장 금지) |
| SESSION_SECRET | 32자 이상 난수, opaque session 키 HMAC에 사용 |
| AUTH_EPOCH | 기존 세션을 무효화하는 운영 버전 |
| SESSION_TTL_SECONDS | 60–86400초, 기본 3600 |
| PUBLIC_ORIGIN | 브라우저가 접속하는 정확한 origin, 끝 `/` 없음 |
| RAG_ENABLED | 기본 false, 현재 adapter 미구현 |

향후 KIS/TOSS/LLM/Telegram 설정은 해당 기능의 구현 단계에만 추가합니다.

## Migration 변경 원칙 및 설계 차이

적용/공유한 Migration은 덮어쓰지 말고 새 revision으로 변경합니다. `alembic revision --autogenerate -m ...`
결과는 반드시 검토하고 별도 테스트 DB에 적용하세요. 운영 DB에는 자동 downgrade/drop을 하지 않습니다.
백업과 expand/contract 호환성을 확인한 단일 Migration runner를 사용하며 API/Worker가 경쟁 실행하지 않습니다.

**DESIGN ISSUE STEP2-DB-01**: 전체 논리 모델의 `trade_execution.order_id`는 `broker_order` FK지만,
사용자가 지정한 이번 11개 테이블에 `broker_order`가 없습니다. 초기 모델에서는 컬럼과 FK를 함께 보류하고
주문 구현 단계의 새 Migration에서 추가합니다. 논리 설계의 테이블/컬럼은 삭제하지 않았습니다.
ORDER_AGGREGATE/FILL 전환 및 주문별 중복 기여 제어는 주문/수집 Service를 구현할 때 완성해야 합니다.
이번 단계에는 체결 입력 API나 Broker 수집 workflow가 없습니다.

다른 장기 설계의 Service 불변조건도 해당 write 경로에서 완성합니다. 현재 PositionRepository는 소유권,
종목 통화, sync 계좌/scope를 검사합니다. 계산 잔고/coverage 대사, 체결과 조정의 write 서비스,
snapshot publish는 후속 단계이며 모델에 직접 쓰는 것만으로 전체 업무 검증이 되는 것은 아닙니다.

## 종료 및 문제 해결

API/Worker/Beat 터미널에서 Ctrl+C 후:

```powershell
docker compose --profile test down
```

named volume은 유지됩니다. `down -v`는 개발 데이터와 Redis 상태를 삭제하므로 일반 종료에 사용하지 마세요.

- `docker`를 못 찾음: Docker Desktop 설치 후 새 터미널을 열고 engine을 시작하세요.
- daemon 연결 실패: Docker Desktop Linux engine/WSL 상태를 확인하세요.
- PG 인증 실패: 기존 volume의 비밀번호는 `.env` 변경으로 자동 변경되지 않습니다. 기존 값을 복원하거나 DB에서 명시적으로 변경하세요.
- 5432/5433/6379 포트 충돌: Compose host port와 해당 URL을 함께 바꾸세요.
- Admin 503: 환경설정, PG/Redis 상태, Migration, bootstrap 순서 확인. DB 예외 원문/비밀은 HTTP에 노출하지 않습니다.
- 로그인 403: `PUBLIC_ORIGIN`, CSRF cookie, 브라우저 주소 확인. HTTPS 설정에서 HTTP 접속하면 Secure cookie가 전송되지 않습니다.
- 로그인 429: 마지막 제한 창이 끝날 때까지 최대 60초 기다리세요.
- extension 권한 실패: DB 관리자에게 `btree_gist` 설치를 요청하세요.
- Queue timeout: worker의 큐 이름, Redis 주소, Windows 실행 제한을 확인하세요.

## 설계 문서

[PHASE1_SPEC](docs/PHASE1_SPEC.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) ·
[DB_DESIGN](docs/DB_DESIGN.md) · [API_SPEC](docs/API_SPEC.md) ·
[AGENT_DESIGN](docs/AGENT_DESIGN.md) · [DEPLOYMENT](docs/DEPLOYMENT.md) ·
[DECISIONS](docs/DECISIONS.md) · [ROADMAP](docs/ROADMAP.md)

전체 Phase 1 논리 모델 26개 테이블은 유지합니다. 이번 Initial Migration은 11개만 구현하며
Market/News/Disclosure/Macro/Event/Agent/Alert/Conversation/Thesis/RAG는 기능별 후속 Migration으로 추가합니다.
Railway, Static Outbound IP, Qdrant 운영 선택은 D3 Deferred 그대로입니다.

## 현재 검증 상태 — 2026-10-05

- 의존성 설치/`pip check`, ruff, format, mypy: 통과.
- pytest 전체 **34개 통과**, 보류/skip 없음: unit/API 15개 + PostgreSQL/Redis 통합 19개. 실제 의존성을 사용하는 테스트 계정 로그인/로그아웃도 검증했습니다.
- 실제 Uvicorn startup, `/health/live`, `/health/ready`: 모두 200. PG/Redis 정상, RAG DISABLED 확인.
- 실제 PostgreSQL `alembic upgrade head` 및 `alembic check`: 통과. 업무 11개 + Alembic 이력 1개 확인. 격리 테스트 schema에서 downgrade/upgrade, FK/제약/Repository/동시성 검증 통과.
- 최초 실제 적용에서 instrument.active의 boolean 기본값이 정수 1로 렌더링된 오류를 발견했습니다. 아직 적용되지 않았던 initial revision을 `sa.true()`로 수정하고 SQL 회귀 검사를 추가했습니다.
- 별도 Celery Worker 프로세스의 Redis health task 전달/결과 수신 및 별도 Beat 프로세스 기동 확인. Beat schedule은 비어 있으며 실제 업무 스케줄은 검증 범위 밖입니다.
- 사용자 설정의 Admin credential 구성 완료 확인, ACTIVE app_user bootstrap 완료. 실제 사용자 비밀번호를 읽거나 변경하지 않았습니다.
- GitHub Actions 원격 실행은 아직 하지 않았습니다. TestClient의 httpx deprecation 경고가 남아 있습니다. 최초 전체 테스트의 샌드박스 캐시 쓰기 경고는 테스트 실패가 아니며 후속 검사는 별도 쓰기 가능한 캐시 또는 캐시 비활성 옵션으로 수행했습니다.

검증용 API/Worker/Beat 프로세스는 종료했습니다. PostgreSQL/Redis 및 테스트 DB 컨테이너는 실행 상태로 유지했습니다. 실제 Admin 화면을 사용하려면 위 API 실행 명령으로 시작하세요.
