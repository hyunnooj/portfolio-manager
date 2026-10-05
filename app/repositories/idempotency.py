from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import IdempotencyRequest


class IdempotencyRepository:
    def __init__(self, session: Session):
        self.session = session

    def reserve(
        self, user_id: UUID, operation: str, key: str, request_hash: str
    ) -> tuple[IdempotencyRequest, bool]:
        inserted = self.session.scalar(
            insert(IdempotencyRequest)
            .values(
                id=uuid4(),
                user_id=user_id,
                operation=operation,
                idempotency_key=key,
                request_hash=request_hash,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "operation", "idempotency_key"])
            .returning(IdempotencyRequest.id)
        )
        row = self.session.scalars(
            select(IdempotencyRequest)
            .where(
                IdempotencyRequest.user_id == user_id,
                IdempotencyRequest.operation == operation,
                IdempotencyRequest.idempotency_key == key,
            )
            .with_for_update()
        ).one()
        return row, inserted is not None
