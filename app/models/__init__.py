"""STEP 2 Portfolio Foundation; later domains arrive in separate migrations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.types import ExactNumeric, UTCDateTime


class Base(DeclarativeBase):
    metadata = sa.MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        str: sa.Text,
        datetime: UTCDateTime(),
        Decimal: ExactNumeric(),
        dict[str, Any]: JSONB,
    }


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())


class Updated:
    updated_at: Mapped[datetime] = mapped_column(
        server_default=sa.func.now(), onupdate=sa.func.now()
    )


def choice(column: str, values: str) -> sa.CheckConstraint:
    quoted = ", ".join(repr(value) for value in values.split())
    return sa.CheckConstraint(f"{column} IN ({quoted})", name=f"ck_{column}_allowed")


def fk(table: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{table}.id", ondelete="RESTRICT")


class AppUser(Record, Updated, Base):
    __tablename__ = "app_user"
    display_name: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="ACTIVE")
    __table_args__ = (choice("status", "ACTIVE DISABLED"),)


class BrokerAccount(Record, Updated, Base):
    __tablename__ = "broker_account"
    user_id: Mapped[UUID] = mapped_column(fk("app_user"))
    broker: Mapped[str]
    account_key: Mapped[str]
    label: Mapped[str]
    masked_account: Mapped[str | None]
    credential_ref: Mapped[str | None]
    external_account_ref_ciphertext: Mapped[bytes | None]
    source_mode: Mapped[str]
    capabilities: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(server_default="PENDING")
    last_success_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(sa.BigInteger, server_default="1")
    __table_args__ = (
        sa.UniqueConstraint("user_id", "broker", "account_key"),
        choice("broker", "KIS TOSS MANUAL"),
        choice("source_mode", "BROKER_API MANUAL"),
        choice("status", "ACTIVE DEGRADED DISABLED PENDING"),
        sa.CheckConstraint("version >= 1", name="ck_account_version"),
    )


class Instrument(Record, Updated, Base):
    __tablename__ = "instrument"
    symbol: Mapped[str]
    name: Mapped[str]
    mic: Mapped[str]
    asset_type: Mapped[str]
    currency: Mapped[str] = mapped_column(sa.CHAR(3))
    market_timezone: Mapped[str]
    isin: Mapped[str | None]
    cik: Mapped[str | None] = mapped_column(index=True)
    dart_corp_code: Mapped[str | None] = mapped_column(index=True)
    active: Mapped[bool] = mapped_column(server_default=sa.true())
    __table_args__ = (
        sa.Index("ix_instrument_symbol_mic", "symbol", "mic"),
        choice("asset_type", "EQUITY ETF"),
    )


class BrokerInstrumentMap(Record, Base):
    __tablename__ = "broker_instrument_map"
    broker: Mapped[str]
    external_symbol: Mapped[str]
    external_market: Mapped[str]
    instrument_id: Mapped[UUID] = mapped_column(fk("instrument"), index=True)
    valid_from: Mapped[datetime]
    valid_to: Mapped[datetime | None]
    mapping_source: Mapped[str]
    __table_args__ = (
        sa.UniqueConstraint("broker", "external_symbol", "external_market", "valid_from"),
        sa.Index(
            "uq_map_current",
            "broker",
            "external_symbol",
            "external_market",
            unique=True,
            postgresql_where=sa.text("valid_to IS NULL"),
        ),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_map_period"),
        ExcludeConstraint(
            ("broker", "="),
            ("external_symbol", "="),
            ("external_market", "="),
            (sa.func.tstzrange(sa.column("valid_from"), sa.column("valid_to"), "[)"), "&&"),
            name="ex_map_period",
            using="gist",
        ),
    )


class SyncRun(Record, Base):
    __tablename__ = "sync_run"
    account_id: Mapped[UUID | None] = mapped_column(fk("broker_account"))
    provider: Mapped[str]
    scope: Mapped[str]
    request_key: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default="QUEUED")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    window_from: Mapped[datetime | None]
    window_to: Mapped[datetime | None]
    coverage: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    snapshot: Mapped[dict[str, Any] | None]
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None]
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    error_code: Mapped[str | None]
    __table_args__ = (
        choice("status", "QUEUED RUNNING SUCCEEDED PARTIAL FAILED"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_sync_attempt"),
        sa.CheckConstraint("window_to >= window_from", name="ck_sync_window"),
        sa.CheckConstraint("finished_at >= started_at", name="ck_sync_finish"),
        sa.Index(
            "ix_sync_account_scope_created", "account_id", "scope", sa.text("created_at DESC")
        ),
        sa.Index(
            "ix_sync_pending",
            "status",
            "lease_until",
            postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )


class AccountPosition(Record, Base):
    __tablename__ = "account_position"
    account_id: Mapped[UUID] = mapped_column(fk("broker_account"))
    instrument_id: Mapped[UUID] = mapped_column(fk("instrument"), index=True)
    scope: Mapped[str]
    quantity: Mapped[Decimal]
    available_quantity: Mapped[Decimal | None]
    avg_cost: Mapped[Decimal | None]
    currency: Mapped[str] = mapped_column(sa.CHAR(3))
    quantity_basis: Mapped[str]
    source: Mapped[str]
    as_of: Mapped[datetime]
    as_of_basis: Mapped[str]
    observed_at: Mapped[datetime]
    sync_run_id: Mapped[UUID | None] = mapped_column(fk("sync_run"), index=True)
    quality: Mapped[str]
    version: Mapped[int] = mapped_column(sa.BigInteger, server_default="1")
    __table_args__ = (
        sa.UniqueConstraint("account_id", "scope", "instrument_id"),
        choice("quantity_basis", "TRADE_TIME SETTLED UNKNOWN"),
        choice("source", "BROKER_API MANUAL"),
        choice("as_of_basis", "BROKER OBSERVED"),
        choice("quality", "GOOD STALE UNKNOWN"),
        sa.CheckConstraint(
            "quantity >= 0 AND (available_quantity IS NULL OR available_quantity >= 0) AND (avg_cost IS NULL OR avg_cost >= 0)",
            name="ck_position_amounts",
        ),
        sa.CheckConstraint("version >= 1", name="ck_position_version"),
    )


class TradeExecution(Record, Updated, Base):
    __tablename__ = "trade_execution"
    # order_id and its FK arrive together with broker_order in a later migration.
    account_id: Mapped[UUID] = mapped_column(fk("broker_account"))
    instrument_id: Mapped[UUID] = mapped_column(fk("instrument"), index=True)
    source: Mapped[str]
    granularity: Mapped[str]
    identity_key: Mapped[str]
    external_execution_id: Mapped[str | None]
    side: Mapped[str]
    quantity: Mapped[Decimal]
    price: Mapped[Decimal]
    gross_amount: Mapped[Decimal | None]
    currency: Mapped[str] = mapped_column(sa.CHAR(3))
    fee: Mapped[Decimal | None]
    tax: Mapped[Decimal | None]
    executed_at: Mapped[datetime | None]
    trade_date: Mapped[date]
    source_timezone: Mapped[str]
    time_precision: Mapped[str]
    state: Mapped[str] = mapped_column(server_default="ACTIVE")
    revision: Mapped[int] = mapped_column(server_default="1")
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    sync_run_id: Mapped[UUID | None] = mapped_column(fk("sync_run"), index=True)
    __table_args__ = (
        sa.UniqueConstraint("account_id", "identity_key"),
        sa.Index(
            "ix_trade_account_instrument_date",
            "account_id",
            "instrument_id",
            "trade_date",
            "executed_at",
        ),
        choice("source", "BROKER_API MANUAL"),
        choice("granularity", "FILL ORDER_AGGREGATE"),
        choice("side", "BUY SELL"),
        choice("time_precision", "SECOND MILLISECOND DAY UNKNOWN"),
        choice("state", "ACTIVE VOID"),
        sa.CheckConstraint(
            "quantity > 0 AND price >= 0 AND (fee IS NULL OR fee >= 0) AND (tax IS NULL OR tax >= 0) AND revision >= 1",
            name="ck_trade_amounts",
        ),
    )


class PositionAdjustment(Record, Base):
    __tablename__ = "position_adjustment"
    account_id: Mapped[UUID] = mapped_column(fk("broker_account"))
    instrument_id: Mapped[UUID] = mapped_column(fk("instrument"), index=True)
    kind: Mapped[str]
    quantity_mode: Mapped[str]
    quantity: Mapped[Decimal]
    unit_cost: Mapped[Decimal | None]
    currency: Mapped[str] = mapped_column(sa.CHAR(3))
    effective_at: Mapped[datetime]
    boundary_basis: Mapped[str]
    reason: Mapped[str]
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    entry_key: Mapped[str]
    state: Mapped[str] = mapped_column(server_default="ACTIVE")
    void_reason: Mapped[str | None]
    __table_args__ = (
        sa.UniqueConstraint("account_id", "entry_key"),
        sa.Index(
            "uq_adjustment_opening",
            "account_id",
            "instrument_id",
            "effective_at",
            unique=True,
            postgresql_where=sa.text("state = 'ACTIVE' AND kind = 'OPENING_BALANCE'"),
        ),
        sa.Index(
            "ix_adjustment_effective", "account_id", "instrument_id", sa.text("effective_at DESC")
        ),
        choice("state", "ACTIVE VOID"),
        choice("boundary_basis", "TRADE_TIME SETTLED MANUAL"),
        sa.CheckConstraint(
            "(kind = 'OPENING_BALANCE' AND quantity_mode = 'ABSOLUTE' AND quantity >= 0) OR (kind IN ('TRANSFER', 'SPLIT_CORRECTION', 'OTHER') AND quantity_mode = 'DELTA' AND quantity <> 0)",
            name="ck_adjustment_quantity_mode",
        ),
        sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_adjustment_cost"),
        sa.CheckConstraint(
            "state <> 'VOID' OR (void_reason IS NOT NULL AND length(trim(void_reason)) > 0)",
            name="ck_adjustment_void_reason",
        ),
    )


class ReconciliationResult(Record, Base):
    __tablename__ = "reconciliation_result"
    sync_run_id: Mapped[UUID] = mapped_column(fk("sync_run"))
    account_id: Mapped[UUID] = mapped_column(fk("broker_account"))
    instrument_id: Mapped[UUID] = mapped_column(fk("instrument"), index=True)
    scope: Mapped[str]
    calculated_quantity: Mapped[Decimal | None]
    broker_quantity: Mapped[Decimal]
    difference: Mapped[Decimal | None]
    tolerance: Mapped[Decimal] = mapped_column(server_default="0")
    status: Mapped[str]
    reason_code: Mapped[str]
    basis: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None]
    __table_args__ = (
        sa.UniqueConstraint("sync_run_id", "scope", "instrument_id"),
        sa.Index(
            "ix_reconciliation_account_status_created",
            "account_id",
            "status",
            sa.text("created_at DESC"),
        ),
        choice("status", "MATCH MISMATCH INDETERMINATE"),
        sa.CheckConstraint(
            "broker_quantity >= 0 AND tolerance >= 0", name="ck_reconciliation_amounts"
        ),
        sa.CheckConstraint(
            "(calculated_quantity IS NULL AND difference IS NULL AND status = 'INDETERMINATE') OR (calculated_quantity IS NOT NULL AND difference IS NOT NULL AND difference = broker_quantity - calculated_quantity)",
            name="ck_reconciliation_difference",
        ),
        sa.CheckConstraint(
            "status = 'INDETERMINATE' OR (status = 'MATCH' AND abs(difference) <= tolerance) OR (status = 'MISMATCH' AND abs(difference) > tolerance)",
            name="ck_reconciliation_status",
        ),
    )


class IdempotencyRequest(Record, Base):
    __tablename__ = "idempotency_request"
    user_id: Mapped[UUID] = mapped_column(fk("app_user"))
    operation: Mapped[str]
    idempotency_key: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="IN_PROGRESS")
    response_status: Mapped[int | None] = mapped_column(sa.SmallInteger)
    response_body: Mapped[dict[str, Any] | None]
    resource_type: Mapped[str | None]
    resource_id: Mapped[UUID | None]
    completed_at: Mapped[datetime | None]
    __table_args__ = (
        sa.UniqueConstraint("user_id", "operation", "idempotency_key"),
        sa.Index("ix_idempotency_resource", "resource_type", "resource_id"),
        choice("status", "IN_PROGRESS COMPLETED"),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR (response_status BETWEEN 200 AND 299 AND response_status IS NOT NULL AND response_body IS NOT NULL AND resource_type IS NOT NULL AND resource_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_idempotency_completed",
        ),
    )


class OutboxMessage(Record, Base):
    __tablename__ = "outbox_message"
    user_id: Mapped[UUID | None] = mapped_column(fk("app_user"), index=True)
    event_key: Mapped[str] = mapped_column(unique=True)
    event_type: Mapped[str]
    aggregate_type: Mapped[str]
    aggregate_id: Mapped[UUID]
    payload: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(server_default="PENDING")
    available_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(index=True)
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    last_error_code: Mapped[str | None]
    __table_args__ = (
        choice("status", "PENDING CLAIMED PUBLISHED DONE DEFERRED DEAD"),
        sa.Index("ix_outbox_pending", "status", "available_at"),
        sa.Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt"),
        sa.CheckConstraint(
            "status <> 'CLAIMED' OR (lease_token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_outbox_claim",
        ),
    )
