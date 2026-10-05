import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.auth.session import SessionStore
from app.core.config import Settings
from app.core.db import make_engine, session_factory
from app.models import AppUser
from app.services.rag import DeferredRagGateway


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    engine = make_engine(config)
    redis = Redis.from_url(
        config.redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Infrastructure is checked by readiness, never implicitly migrated at startup.
        yield
        redis.close()
        engine.dispose()

    application = FastAPI(
        title="Portfolio Manager",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[urlsplit(config.public_origin).hostname or "localhost"],
    )
    application.state.settings = config
    application.state.sessions = session_factory(engine)
    application.state.redis = redis
    application.state.rag = DeferredRagGateway(config.rag_enabled)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    def active_user(user_id: UUID) -> bool:
        with application.state.sessions() as session:
            return (
                session.scalar(
                    select(AppUser.id).where(AppUser.id == user_id, AppUser.status == "ACTIVE")
                )
                is not None
            )

    application.state.active_user = active_user

    def database_ready() -> bool:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    application.state.database_ready = database_ready

    @application.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not config.secure_cookie and config.app_env != "test":
            peer = request.client.host if request.client else ""
            if peer not in {"127.0.0.1", "::1"}:
                return JSONResponse({"detail": "LOCAL_HTTP_REQUIRES_LOOPBACK"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        if config.secure_cookie:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @application.exception_handler(RedisError)
    @application.exception_handler(SQLAlchemyError)
    async def infrastructure_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "DEPENDENCY_UNAVAILABLE"}, status_code=503)

    def store() -> SessionStore:
        if not config.auth_configured:
            raise HTTPException(503, "AUTH_NOT_CONFIGURED")
        return SessionStore(application.state.redis, config)

    def csrf_check(request: Request, data: dict | None, submitted: str) -> None:
        if request.headers.get("origin") != config.public_origin:
            raise HTTPException(403, "ORIGIN_REJECTED")
        if not data or not submitted or not hmac.compare_digest(data["csrf"], submitted):
            raise HTTPException(403, "CSRF_REJECTED")

    def authenticated(request: Request) -> dict | None:
        data = store().get("session", request.cookies.get("pm_session", ""))
        if not data or data.get("user_id") != str(config.admin_user_id):
            return None
        if not application.state.active_user(config.admin_user_id):
            return None
        return data

    def cookie(response: RedirectResponse | HTMLResponse, name: str, token: str, ttl: int) -> None:
        response.set_cookie(
            name,
            token,
            max_age=ttl,
            httponly=True,
            secure=config.secure_cookie,
            samesite="strict",
            path="/admin",
        )

    @application.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "LIVE"}

    @application.get("/health/ready")
    def ready() -> JSONResponse:
        checks = {"postgres": False, "redis": False}
        try:
            checks["postgres"] = bool(application.state.database_ready())
        except SQLAlchemyError:
            pass
        try:
            checks["redis"] = bool(application.state.redis.ping())
        except RedisError:
            pass
        healthy = all(checks.values())
        return JSONResponse(
            {
                "status": "READY" if healthy else "NOT_READY",
                "dependencies": checks,
                "rag": asdict(application.state.rag.status()),
            },
            status_code=200 if healthy else 503,
        )

    @application.get("/admin/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        auth = store()
        auth.delete("login", request.cookies.get("pm_login", ""))
        token, csrf = auth.create(authenticated=False)
        response = templates.TemplateResponse(
            request=request, name="login.html", context={"csrf": csrf}
        )
        cookie(response, "pm_login", token, 600)
        return response

    @application.post("/admin/login")
    def login(
        request: Request,
        password: str = Form(..., max_length=1024),
        csrf_token: str = Form(..., max_length=100),
    ) -> RedirectResponse:
        auth = store()
        csrf_check(request, auth.get("login", request.cookies.get("pm_login", "")), csrf_token)
        if not auth.rate_allowed(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "LOGIN_RATE_LIMIT", headers={"Retry-After": "60"})
        if not auth.verify_password(password) or not application.state.active_user(
            config.admin_user_id
        ):
            raise HTTPException(401, "INVALID_CREDENTIALS")
        auth.delete("login", request.cookies.get("pm_login", ""))
        auth.delete("session", request.cookies.get("pm_session", ""))
        token, _ = auth.create(authenticated=True)
        response = RedirectResponse("/admin", status_code=303)
        response.delete_cookie("pm_login", path="/admin")
        cookie(response, "pm_session", token, config.session_ttl_seconds)
        return response

    @application.get("/admin", response_class=HTMLResponse)
    def admin(request: Request) -> Response:
        data = authenticated(request)
        if data is None:
            return RedirectResponse("/admin/login", status_code=303)
        return templates.TemplateResponse(
            request=request, name="admin.html", context={"csrf": data["csrf"]}
        )

    @application.post("/admin/logout")
    def logout(request: Request, csrf_token: str = Form(..., max_length=100)) -> RedirectResponse:
        data = authenticated(request)
        if data is None:
            raise HTTPException(401, "AUTH_REQUIRED")
        csrf_check(request, data, csrf_token)
        store().delete("session", request.cookies.get("pm_session", ""))
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie("pm_session", path="/admin")
        return response

    return application


app = create_app()
