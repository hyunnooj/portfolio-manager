import os
import re
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models import AppUser


@pytest.mark.integration
@pytest.mark.queue
def test_migrated_database_redis_and_admin_flow(db_engine, sessions):
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is required for real dependency API verification")
    from urllib.parse import urlsplit

    if urlsplit(redis_url).path in {"", "/", "/0"}:
        pytest.fail("Use a dedicated nonzero test Redis DB")
    user_id = uuid4()
    with sessions.begin() as session:
        session.add(AppUser(id=user_id, display_name="Integration Fixture"))
    config = Settings(
        _env_file=None,
        app_env="test",
        public_origin="http://testserver",
        database_url=db_engine.url.render_as_string(hide_password=False),
        redis_url=redis_url,
        admin_user_id=user_id,
        admin_password_hash=PasswordHasher().hash("fixture-password"),
        session_secret="x" * 48,
        auth_epoch=uuid4().hex,
    )
    app = create_app(config)
    app.state.sessions = sessions  # Isolated, Alembic-migrated PostgreSQL schema.
    try:
        with TestClient(app, follow_redirects=False) as client:
            ready = client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json()["rag"]["status"] == "DISABLED"
            form = client.get("/admin/login")
            token = re.search(r'name="csrf_token" value="([^"]+)"', form.text).group(1)
            response = client.post(
                "/admin/login",
                data={"password": "fixture-password", "csrf_token": token},
                headers={"Origin": "http://testserver"},
            )
            assert response.status_code == 303
            page = client.get("/admin")
            assert page.status_code == 200
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            assert (
                client.post(
                    "/admin/logout",
                    data={"csrf_token": token},
                    headers={"Origin": "http://testserver"},
                ).status_code
                == 303
            )
            assert client.get("/admin").status_code == 303
    finally:
        # Delete only this test's random auth epoch; never FLUSHDB.
        keys = list(app.state.redis.scan_iter(f"pm:auth:{config.auth_epoch}:*"))
        if keys:
            app.state.redis.delete(*keys)
        app.state.redis.close()
