from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["local", "test", "production"] = "local"
    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/portfolio")
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    admin_user_id: UUID | None = None
    admin_password_hash: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    auth_epoch: str = "1"
    session_ttl_seconds: int = 3600
    public_origin: str = "http://127.0.0.1:8000"
    rag_enabled: bool = False

    @model_validator(mode="before")
    @classmethod
    def blank_identity(cls, values: dict[str, object]) -> dict[str, object]:
        if values.get("admin_user_id") == "":
            values["admin_user_id"] = None
        return values

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        origin = urlsplit(self.public_origin)
        if origin.path or origin.query or origin.fragment or origin.username:
            raise ValueError("PUBLIC_ORIGIN must be an origin without path or credentials")
        if origin.scheme not in {"http", "https"} or not origin.hostname:
            raise ValueError("Invalid PUBLIC_ORIGIN")
        if origin.scheme == "http" and (
            self.app_env == "production"
            or origin.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}
        ):
            raise ValueError("HTTP is permitted only on local development hosts")
        if not 60 <= self.session_ttl_seconds <= 86400:
            raise ValueError("Session TTL must be between 60 and 86400 seconds")
        if (
            self.session_secret.get_secret_value()
            and len(self.session_secret.get_secret_value()) < 32
        ):
            raise ValueError("SESSION_SECRET must be at least 32 characters")
        if self.app_env == "production" and not self.auth_configured:
            raise ValueError("Admin credentials and identity must be configured")
        return self

    @property
    def secure_cookie(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def auth_configured(self) -> bool:
        return bool(
            self.admin_user_id
            and self.admin_password_hash.get_secret_value()
            and self.session_secret.get_secret_value()
        )
