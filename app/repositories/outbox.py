from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import OutboxMessage


class OutboxRepository:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, message: OutboxMessage) -> UUID:
        """Use the caller's business transaction; event_key is a domain identity."""
        values = {
            name: getattr(message, name)
            for name in (
                "user_id",
                "event_key",
                "event_type",
                "aggregate_type",
                "aggregate_id",
                "payload",
            )
        }
        inserted = self.session.scalar(
            insert(OutboxMessage)
            .values(id=uuid4(), **values)
            .on_conflict_do_nothing(index_elements=["event_key"])
            .returning(OutboxMessage.id)
        )
        if inserted is not None:
            return inserted
        existing = self.session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_key == message.event_key)
        ).one()
        if any(getattr(existing, name) != value for name, value in values.items()):
            raise ValueError("Event key reused with different content")
        return existing.id

    def claim(self, limit: int = 20, lease_seconds: int = 60) -> list[OutboxMessage]:
        if not 1 <= limit <= 100 or lease_seconds < 1:
            raise ValueError("Invalid claim limits")
        now = datetime.now(UTC)
        rows = list(
            self.session.scalars(
                select(OutboxMessage)
                .where(
                    or_(
                        and_(OutboxMessage.status == "PENDING", OutboxMessage.available_at <= now),
                        and_(OutboxMessage.status == "CLAIMED", OutboxMessage.lease_until < now),
                    )
                )
                .order_by(OutboxMessage.available_at, OutboxMessage.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            row.status, row.lease_token, row.lease_until = (
                "CLAIMED",
                uuid4(),
                now + timedelta(seconds=lease_seconds),
            )
            row.attempt_count += 1
        self.session.flush()
        return rows

    def finish(self, message_id: UUID, token: UUID, *, published: bool) -> bool:
        result = self.session.scalar(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message_id,
                OutboxMessage.status == "CLAIMED",
                OutboxMessage.lease_token == token,
                OutboxMessage.lease_until > datetime.now(UTC),
            )
            .values(
                status="PUBLISHED" if published else "PENDING",
                lease_token=None,
                lease_until=None,
                available_at=datetime.now(UTC) + timedelta(seconds=30),
                last_error_code=None if published else "PUBLISH_FAILED",
            )
            .returning(OutboxMessage.id)
        )
        return result is not None
