"""Run interactively; updates ignored .env without printing secrets."""

import getpass
import secrets
from pathlib import Path
from uuid import uuid4

from argon2 import PasswordHasher
from dotenv import dotenv_values, set_key


def main() -> None:
    target = Path(".env")
    if not target.exists():
        raise SystemExit("Copy .env.example to .env first.")
    password = getpass.getpass("New admin password (at least 8 characters): ")
    if len(password) < 8 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Password too short or confirmation mismatch. No changes made.")
    values = dotenv_values(target)
    identity = values.get("ADMIN_USER_ID") or str(uuid4())
    set_key(target, "ADMIN_USER_ID", identity)
    set_key(target, "ADMIN_PASSWORD_HASH", PasswordHasher().hash(password))
    set_key(target, "SESSION_SECRET", secrets.token_urlsafe(48))
    print("Admin configuration saved to ignored .env; existing sessions invalidated.")


if __name__ == "__main__":
    main()
