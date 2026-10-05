from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccountPosition, BrokerAccount, Instrument, SyncRun


class PositionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, user_id: UUID, position: AccountPosition) -> None:
        account = self.session.get(BrokerAccount, position.account_id)
        instrument = self.session.get(Instrument, position.instrument_id)
        if account is None or account.user_id != user_id:
            raise LookupError("Account not found")
        if instrument is None or instrument.currency != position.currency:
            raise ValueError("Instrument currency mismatch")
        if position.sync_run_id is not None:
            run = self.session.get(SyncRun, position.sync_run_id)
            if run is None or (run.account_id, run.scope) != (position.account_id, position.scope):
                raise ValueError("Sync account/scope mismatch")
        self.session.add(position)
        self.session.flush()

    def quantities(self, user_id: UUID, scope: str) -> dict[UUID, Decimal]:
        # Each account/scope/instrument is unique; no symbol-based joining or FX conversion.
        rows = self.session.execute(
            select(AccountPosition.instrument_id, func.sum(AccountPosition.quantity))
            .join(BrokerAccount, BrokerAccount.id == AccountPosition.account_id)
            .where(BrokerAccount.user_id == user_id, AccountPosition.scope == scope)
            .group_by(AccountPosition.instrument_id)
        )
        return {instrument_id: quantity for instrument_id, quantity in rows}
