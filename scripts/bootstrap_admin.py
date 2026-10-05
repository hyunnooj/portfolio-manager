"""Explicit identity bootstrap after migrations; never runs during app startup."""

from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings
from app.core.db import make_engine, session_factory
from app.models import AppUser


def main() -> None:
    settings = Settings()
    if not settings.auth_configured:
        raise SystemExit("Run python -m scripts.configure_admin first.")
    engine = make_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            session.execute(
                insert(AppUser)
                .values(id=settings.admin_user_id, display_name="Admin")
                .on_conflict_do_nothing(index_elements=["id"])
            )
            user = session.get(AppUser, settings.admin_user_id)
            if user is None or user.status != "ACTIVE":
                raise SystemExit("Configured user is disabled; bootstrap will not reactivate it.")
        print("Admin identity exists and is ACTIVE.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
