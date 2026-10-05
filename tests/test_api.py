import re
from uuid import uuid4

import fakeredis
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.auth.session import SessionStore
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    config = Settings(
        _env_file=None,
        app_env="test",
        public_origin="http://testserver",
        admin_user_id=uuid4(),
        admin_password_hash=PasswordHasher().hash("test-password-only"),
        session_secret="x" * 48,
    )
    application = create_app(config)
    application.state.redis = fakeredis.FakeRedis(decode_responses=True)
    application.state.database_ready = lambda: True
    application.state.active_user = lambda user_id: user_id == config.admin_user_id
    with TestClient(application, follow_redirects=False) as client:
        yield client


def csrf(response):
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def login(client, password="test-password-only"):
    token = csrf(client.get("/admin/login"))
    return client.post(
        "/admin/login",
        data={"csrf_token": token, "password": password},
        headers={"Origin": "http://testserver"},
    )


def test_health_and_startup_without_qdrant(client):
    assert client.get("/health/live").json() == {"status": "LIVE"}
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["rag"] == {"enabled": False, "status": "DISABLED"}
    client.app.state.rag.enabled = True
    assert client.get("/health/ready").json()["rag"]["status"] == "UNAVAILABLE"


def test_readiness_dependency_failure_does_not_break_liveness(client):
    def offline():
        raise OperationalError("probe", None, Exception("private details"))

    client.app.state.database_ready = offline
    assert client.get("/health/ready").status_code == 503
    assert "private" not in client.get("/health/ready").text
    assert client.get("/health/live").status_code == 200


def test_login_logout_cookies_and_session_invalidation(client):
    assert client.get("/admin").status_code == 303
    response = login(client)
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    previous = client.cookies.get("pm_session")
    page = client.get("/admin")
    assert page.status_code == 200
    response = client.post(
        "/admin/logout", data={"csrf_token": csrf(page)}, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 303
    client.cookies.set("pm_session", previous, path="/admin")
    assert client.get("/admin").status_code == 303


def test_csrf_origin_and_rate_limit(client):
    token = csrf(client.get("/admin/login"))
    data = {"csrf_token": token, "password": "wrong"}
    assert client.post("/admin/login", data=data).status_code == 403
    assert (
        client.post(
            "/admin/login", data=data, headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/admin/login",
            data={**data, "csrf_token": "bad"},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 403
    )
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    assert login(client).status_code == 429


def test_disabled_identity_and_expired_sessions(client):
    assert login(client).status_code == 303
    client.app.state.active_user = lambda _: False
    assert client.get("/admin").status_code == 303
    assert login(client).status_code == 401
    client.app.state.active_user = lambda _: True
    assert login(client).status_code == 303
    auth = SessionStore(client.app.state.redis, client.app.state.settings)
    key = auth.key("session", client.cookies.get("pm_session"))
    assert 0 < client.app.state.redis.ttl(key) <= 3600
    client.app.state.redis.expireat(key, 1)
    assert client.get("/admin").status_code == 303


def test_auth_epoch_invalidates_session(client):
    assert login(client).status_code == 303
    client.app.state.settings.auth_epoch = "2"
    assert client.get("/admin").status_code == 303


def test_redis_failure_fails_closed(client, monkeypatch):
    assert login(client).status_code == 303

    def fail(*args, **kwargs):
        raise RedisConnectionError("secret connection details")

    monkeypatch.setattr(client.app.state.redis, "get", fail)
    assert client.get("/admin").status_code == 503
    assert "secret connection" not in client.get("/admin").text


def test_https_cookie_and_http_remote_rejection():
    config = Settings(
        _env_file=None,
        app_env="test",
        public_origin="https://testserver",
        admin_user_id=uuid4(),
        admin_password_hash="hash",
        session_secret="x" * 48,
    )
    app = create_app(config)
    app.state.redis = fakeredis.FakeRedis(decode_responses=True)
    with TestClient(app, base_url="https://testserver") as client:
        assert "Secure" in client.get("/admin/login").headers["set-cookie"]
    local = create_app(Settings(_env_file=None))
    with TestClient(local, base_url="http://127.0.0.1", client=("192.0.2.1", 123)) as client:
        assert client.get("/health/live").status_code == 403
