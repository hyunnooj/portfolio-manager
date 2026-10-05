import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.repositories.idempotency import IdempotencyRepository


class IdempotencyConflict(Exception):
    """HTTP adapters should map to 409 without exposing database details."""


class RequestInProgress(IdempotencyConflict):
    pass


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: dict[str, Any]
    resource_type: str
    resource_id: UUID


def request_digest(*, path: dict[str, str], body: dict[str, Any], query: dict[str, str]) -> str:
    """Hash validated JSON only; caller excludes credentials, cookies and CSRF tokens.

    Decimal/UUID/datetime must already be normalized to API strings, never floats.
    """
    canonical = json.dumps(
        {"path": path, "body": body, "query": query},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyService:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def execute(
        self,
        user_id: UUID,
        operation: str,
        key: str,
        request_hash: str,
        action: Callable[[Session], StoredResponse],
    ) -> StoredResponse:
        if not key or len(key) > 200 or not operation or len(request_hash) != 64:
            raise ValueError("Invalid idempotency identity")
        try:
            with self.sessions.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                row, inserted = IdempotencyRepository(session).reserve(
                    user_id, operation, key, request_hash
                )
                if row.request_hash != request_hash:
                    raise IdempotencyConflict("IDEMPOTENCY_KEY_REUSED")
                if not inserted:
                    if row.status != "COMPLETED":
                        raise RequestInProgress("REQUEST_IN_PROGRESS")
                    assert row.response_status is not None and row.response_body is not None
                    assert row.resource_type is not None and row.resource_id is not None
                    return StoredResponse(
                        row.response_status, row.response_body, row.resource_type, row.resource_id
                    )
                # Action may flush but must never commit or perform external side effects.
                result = action(session)
                if not 200 <= result.status <= 299:
                    raise ValueError("Only successful responses are persisted")
                row.status = "COMPLETED"
                row.response_status, row.response_body = result.status, result.body
                row.resource_type, row.resource_id = result.resource_type, result.resource_id
                row.completed_at = datetime.now(UTC)
                return result
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise RequestInProgress("REQUEST_IN_PROGRESS") from None
            raise
