from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.models import OutboxMessage
from app.repositories.outbox import OutboxRepository


class OutboxPublisher:
    """Minimal at-least-once transport boundary; not registered as a production job.

    Consumers must deduplicate event_key. Broker ACK is not consumer completion.
    """

    def __init__(self, sessions: sessionmaker[Session], send: Callable[[OutboxMessage], None]):
        self.sessions, self.send = sessions, send

    def publish_batch(self, limit: int = 20) -> int:
        with self.sessions.begin() as session:
            messages = OutboxRepository(session).claim(limit)
        acknowledged = 0
        for message in messages:
            assert message.lease_token is not None
            try:
                self.send(message)
                published = True
            except Exception:
                # Do not persist exception strings containing credentials or raw responses.
                published = False
            with self.sessions.begin() as session:
                changed = OutboxRepository(session).finish(
                    message.id, message.lease_token, published=published
                )
                acknowledged += int(changed and published)
        return acknowledged
