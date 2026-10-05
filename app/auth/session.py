import hashlib
import hmac
import json
import secrets
import time
from typing import Any, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from redis import Redis

from app.core.config import Settings


class SessionStore:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis, self.settings = redis, settings

    def key(self, kind: str, token: str) -> str:
        digest = hmac.new(
            self.settings.session_secret.get_secret_value().encode(), token.encode(), hashlib.sha256
        ).hexdigest()
        return f"pm:auth:{self.settings.auth_epoch}:{kind}:{digest}"

    def create(self, *, authenticated: bool) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        kind = "session" if authenticated else "login"
        ttl = self.settings.session_ttl_seconds if authenticated else 600
        self.redis.set(
            self.key(kind, token),
            json.dumps(
                {
                    "csrf": csrf,
                    "user_id": str(self.settings.admin_user_id) if authenticated else None,
                }
            ),
            ex=ttl,
        )
        return token, csrf

    def get(self, kind: str, token: str) -> dict[str, Any] | None:
        if not token or len(token) > 100:
            return None
        value = self.redis.get(self.key(kind, token))
        return json.loads(cast(str, value)) if value else None

    def delete(self, kind: str, token: str) -> None:
        if token:
            self.redis.delete(self.key(kind, token))

    def rate_allowed(self, client: str) -> bool:
        # Fixed windows; both IP and global limits protect this single-admin entry point.
        window = int(time.time()) // 60
        keys = [self.key("rate", f"{window}:{client}"), self.key("rate", f"{window}:global")]
        with self.redis.pipeline(transaction=True) as pipe:
            for key in keys:
                pipe.incr(key)
                pipe.expire(key, 120)
            counts = pipe.execute()
        return counts[0] <= 5 and counts[2] <= 30

    def verify_password(self, password: str) -> bool:
        if not password or len(password) > 1024:
            return False
        try:
            return PasswordHasher().verify(
                self.settings.admin_password_hash.get_secret_value(), password
            )
        except (VerificationError, InvalidHashError):
            return False
