"""Generate local-only infrastructure settings; never overwrite existing .env."""

import secrets
from pathlib import Path


def main() -> None:
    destination = Path(".env")
    content = Path(".env.example").read_text(encoding="utf-8")
    content = content.replace("CHANGE_ME_LOCAL", secrets.token_urlsafe(24))
    try:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError:
        raise SystemExit(".env already exists; left unchanged.") from None
    print("Created ignored .env with a random local database password. Configure admin separately.")


if __name__ == "__main__":
    main()
