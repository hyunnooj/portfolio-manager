from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.models import (
    AccountPosition,
    AppUser,
    Base,
    BrokerAccount,
    BrokerInstrumentMap,
    IdempotencyRequest,
    Instrument,
    OutboxMessage,
    PositionAdjustment,
    ReconciliationResult,
    SyncRun,
    TradeExecution,
)
from app.repositories.outbox import OutboxRepository
from app.repositories.portfolio import PositionRepository
from app.services.idempotency import IdempotencyConflict, IdempotencyService, StoredResponse
from app.services.outbox import OutboxPublisher

pytestmark = pytest.mark.integration


@pytest.fixture
def roots(sessions):
    with sessions.begin() as session:
        user, other = AppUser(display_name="Admin"), AppUser(display_name="Future User")
        instrument = Instrument(
            symbol="AAPL",
            name="Apple",
            mic="XNAS",
            asset_type="EQUITY",
            currency="USD",
            market_timezone="America/New_York",
        )
        session.add_all([user, other, instrument])
        session.flush()
        kis = BrokerAccount(
            user_id=user.id,
            broker="KIS",
            account_key="synthetic-kis",
            label="KIS",
            source_mode="BROKER_API",
        )
        toss = BrokerAccount(
            user_id=user.id,
            broker="TOSS",
            account_key="synthetic-toss",
            label="Toss",
            source_mode="BROKER_API",
        )
        session.add_all([kis, toss])
        session.flush()
        return user.id, other.id, instrument.id, kis.id, toss.id


def position(account, instrument, quantity, **overrides):
    values = dict(
        account_id=account,
        instrument_id=instrument,
        scope="US_EQUITY",
        quantity=Decimal(quantity),
        currency="USD",
        quantity_basis="TRADE_TIME",
        source="BROKER_API",
        as_of=datetime.now(UTC),
        as_of_basis="BROKER",
        observed_at=datetime.now(UTC),
        quality="GOOD",
    )
    return AccountPosition(**(values | overrides))


def adjustment(account, instrument, **overrides):
    values = dict(
        account_id=account,
        instrument_id=instrument,
        kind="OPENING_BALANCE",
        quantity_mode="ABSOLUTE",
        quantity=Decimal("10"),
        currency="USD",
        effective_at=datetime.now(UTC),
        boundary_basis="TRADE_TIME",
        reason="Fixture only",
        entry_key=str(uuid4()),
    )
    return PositionAdjustment(**(values | overrides))


def test_migration_roundtrip_schema_and_no_drift(db_engine):
    with db_engine.begin() as connection:
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        for table in Base.metadata.tables:
            assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert differences == []
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        assert len(inspect(connection).get_table_names()) == 12


def test_two_brokers_same_instrument_and_ownership(sessions, roots):
    user, other, instrument, kis, toss = roots
    with sessions.begin() as session:
        repository = PositionRepository(session)
        repository.add(user, position(kis, instrument, "5"))
        repository.add(user, position(toss, instrument, "10"))
        assert repository.quantities(user, "US_EQUITY") == {instrument: Decimal("15")}
        assert repository.quantities(other, "US_EQUITY") == {}
        assert session.scalar(select(func.count()).select_from(AccountPosition)) == 2
        with pytest.raises(LookupError):
            repository.add(other, position(kis, instrument, "1"))
        with pytest.raises(ValueError, match="currency"):
            repository.add(user, position(kis, instrument, "1", currency="KRW"))
    with sessions() as session:
        row = session.scalars(select(AccountPosition)).first()
        assert isinstance(row.quantity, Decimal)
        assert row.as_of.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "change",
    [
        {"quantity_mode": "DELTA"},
        {"quantity": Decimal("-1")},
        {"kind": "TRANSFER", "quantity_mode": "ABSOLUTE"},
        {"kind": "TRANSFER", "quantity_mode": "DELTA", "quantity": Decimal("0")},
        {"state": "VOID"},
        {"state": "VOID", "void_reason": " "},
    ],
)
def test_invalid_adjustment_constraints(sessions, roots, change):
    _, _, instrument, kis, _ = roots
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(adjustment(kis, instrument, **change))


def test_opening_uniqueness_and_valid_signed_delta(sessions, roots):
    _, _, instrument, kis, _ = roots
    instant = datetime.now(UTC)
    with sessions.begin() as session:
        session.add(adjustment(kis, instrument, effective_at=instant))
        session.add(
            adjustment(
                kis, instrument, kind="TRANSFER", quantity_mode="DELTA", quantity=Decimal("-1")
            )
        )
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(adjustment(kis, instrument, effective_at=instant))


def test_mapping_period_exclusion_and_adjacent_interval(sessions, roots):
    _, _, instrument, _, _ = roots
    start = datetime.now(UTC)

    def mapping(begin, end):
        return BrokerInstrumentMap(
            broker="KIS",
            external_symbol="AAPL",
            external_market="NASDAQ",
            instrument_id=instrument,
            valid_from=begin,
            valid_to=end,
            mapping_source="TEST",
        )

    with sessions.begin() as session:
        session.add(mapping(start, start + timedelta(days=1)))
        session.add(mapping(start + timedelta(days=1), None))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(mapping(start + timedelta(hours=1), start + timedelta(hours=2)))


def test_financial_fk_unique_and_positive_quantity(sessions, roots):
    user, _, instrument, kis, _ = roots
    with sessions.begin() as session:
        PositionRepository(session).add(user, position(kis, instrument, "5"))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(position(kis, instrument, "10"))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(position(kis, instrument, "-1", scope="ANOTHER"))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.delete(session.get(AppUser, user))
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(
            TradeExecution(
                account_id=kis,
                instrument_id=instrument,
                source="MANUAL",
                granularity="FILL",
                identity_key="MANUAL:FILL:test",
                side="BUY",
                quantity=Decimal("0"),
                price=Decimal("1"),
                currency="USD",
                trade_date=datetime.now(UTC).date(),
                source_timezone="UTC",
                time_precision="DAY",
            )
        )


def test_sync_scope_and_reconciliation_difference(sessions, roots):
    user, _, instrument, kis, toss = roots
    with sessions.begin() as session:
        run = SyncRun(account_id=toss, provider="TOSS", scope="US_EQUITY", request_key="sync:test")
        session.add(run)
        session.flush()
        run_id = run.id
        with pytest.raises(ValueError, match="Sync"):
            PositionRepository(session).add(
                user, position(kis, instrument, "1", sync_run_id=run_id)
            )
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.add(
            ReconciliationResult(
                sync_run_id=run_id,
                account_id=toss,
                instrument_id=instrument,
                scope="US_EQUITY",
                calculated_quantity=Decimal("14"),
                broker_quantity=Decimal("15"),
                difference=Decimal("0"),
                status="MATCH",
                reason_code="TEST",
            )
        )


def test_idempotency_replay_conflict_and_atomic_outbox(sessions, roots):
    user, _, instrument, kis, _ = roots
    service = IdempotencyService(sessions)
    calls = []

    def action(session):
        calls.append(1)
        row = adjustment(kis, instrument)
        session.add(row)
        session.flush()
        OutboxRepository(session).enqueue(
            OutboxMessage(
                user_id=user,
                event_key=f"adjustment:{row.id}:1:reconcile",
                event_type="adjustment.created",
                aggregate_type="position_adjustment",
                aggregate_id=row.id,
                payload={"version": 1, "target_id": str(row.id)},
            )
        )
        return StoredResponse(202, {"id": str(row.id)}, "position_adjustment", row.id)

    first = service.execute(user, "v1:POST:/adjustments", "key", "a" * 64, action)
    assert service.execute(user, "v1:POST:/adjustments", "key", "a" * 64, action) == first
    assert len(calls) == 1
    with pytest.raises(IdempotencyConflict):
        service.execute(user, "v1:POST:/adjustments", "key", "b" * 64, action)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
        assert session.scalar(select(func.count()).select_from(IdempotencyRequest)) == 1


def test_idempotency_rollback_does_not_poison_retry(sessions, roots):
    user, _, instrument, kis, _ = roots

    def failing(session):
        session.add(adjustment(kis, instrument))
        session.flush()
        OutboxRepository(session).enqueue(
            OutboxMessage(
                user_id=user,
                event_key="rollback:event",
                event_type="test",
                aggregate_type="fixture",
                aggregate_id=user,
                payload={"version": 1},
            )
        )
        raise RuntimeError("Simulated failure")

    with pytest.raises(RuntimeError):
        IdempotencyService(sessions).execute(user, "create", "rollback", "a" * 64, failing)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(IdempotencyRequest)) == 0
        assert session.scalar(select(func.count()).select_from(PositionAdjustment)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_concurrent_idempotency_has_one_winner(sessions, roots):
    user = roots[0]
    entered, release = Event(), Event()
    service = IdempotencyService(sessions)
    calls = []

    def action(session):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return StoredResponse(202, {"status": "accepted"}, "fixture", user)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.execute, user, "op", "race", "a" * 64, action)
        assert entered.wait(5)
        second = executor.submit(service.execute, user, "op", "race", "a" * 64, action)
        release.set()
        assert first.result() == second.result()
    assert calls == [1]


def test_outbox_claim_retry_fencing_and_deferred(sessions, roots):
    user = roots[0]
    message = OutboxMessage(
        user_id=user,
        event_key="test:event:1",
        event_type="test",
        aggregate_type="fixture",
        aggregate_id=user,
        payload={"version": 1, "target_id": str(user)},
    )
    with sessions.begin() as session:
        repo = OutboxRepository(session)
        message_id = repo.enqueue(message)
        assert repo.enqueue(message) == message_id
    with sessions.begin() as session:
        claimed = OutboxRepository(session).claim()
        old_token = claimed[0].lease_token
        assert len(claimed) == 1
    with sessions.begin() as session:
        repo = OutboxRepository(session)
        assert repo.claim() == []
        assert not repo.finish(message_id, uuid4(), published=True)
        row = session.get(OutboxMessage, message_id)
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with sessions.begin() as session:
        repo = OutboxRepository(session)
        reclaimed = repo.claim()[0]
        new_token = reclaimed.lease_token
        assert new_token != old_token
        assert not repo.finish(message_id, old_token, published=True)
        assert repo.finish(message_id, new_token, published=False)
    with sessions.begin() as session:
        row = session.get(OutboxMessage, message_id)
        row.status = "DEFERRED"
    assert (
        OutboxPublisher(sessions, lambda _: pytest.fail("Deferred event was sent")).publish_batch()
        == 0
    )


def test_outbox_publisher_acknowledges_broker_only(sessions, roots):
    user = roots[0]
    with sessions.begin() as session:
        message_id = OutboxRepository(session).enqueue(
            OutboxMessage(
                user_id=user,
                event_key="test:publish:1",
                event_type="test",
                aggregate_type="fixture",
                aggregate_id=user,
                payload={"version": 1},
            )
        )
    sent = []
    assert (
        OutboxPublisher(sessions, lambda message: sent.append(message.event_key)).publish_batch()
        == 1
    )
    assert sent == ["test:publish:1"]
    with sessions() as session:
        assert session.get(OutboxMessage, message_id).status == "PUBLISHED"
