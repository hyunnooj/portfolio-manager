from io import StringIO
from uuid import uuid4

import pytest
from alembic.config import Config
from pydantic import ValidationError

from alembic import command
from app.core.config import Settings
from app.jobs.celery_app import celery_app, health_task
from app.models import Base
from app.models.types import ExactNumeric, UTCDateTime
from app.services.idempotency import request_digest
from app.services.rag import DeferredRagGateway

TABLES = {
    "app_user",
    "broker_account",
    "instrument",
    "broker_instrument_map",
    "account_position",
    "trade_execution",
    "position_adjustment",
    "sync_run",
    "reconciliation_result",
    "idempotency_request",
    "outbox_message",
}


def test_migration_exact_scope_and_offline_sql():
    assert set(Base.metadata.tables) == TABLES
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    for table in TABLES:
        assert f"CREATE TABLE {table} (" in sql
    assert sql.count("CREATE TABLE ") == 12  # 11 domain tables plus Alembic's own history.
    assert "broker_order" not in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql and "NUMERIC(28, 10)" in sql
    assert "EXCLUDE USING gist" in sql
    assert "active BOOLEAN DEFAULT true NOT NULL" in sql


def test_request_digest_canonical_and_target_sensitive():
    first = request_digest(path={"id": "1"}, body={"b": 2, "a": "1.5"}, query={})
    assert first == request_digest(path={"id": "1"}, body={"a": "1.5", "b": 2}, query={})
    assert first != request_digest(path={"id": "2"}, body={"a": "1.5", "b": 2}, query={})
    with pytest.raises(ValueError):
        request_digest(path={}, body={"invalid": float("nan")}, query={})


@pytest.mark.parametrize("enabled,status", [(False, "DISABLED"), (True, "UNAVAILABLE")])
def test_rag_without_qdrant(enabled, status):
    assert DeferredRagGateway(enabled).search("anything").status == status


def test_configuration_rejects_remote_plaintext_and_missing_production_secrets():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, public_origin="http://example.com")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            public_origin="https://example.com",
            admin_user_id=uuid4(),
        )


def test_celery_task_contract():
    assert health_task.apply().get() == {"status": "OK"}
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.beat_schedule == {}


def test_financial_precision_and_timezone_validation():
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy.dialects.postgresql import dialect

    numeric = ExactNumeric()
    assert numeric.process_bind_param(Decimal("0.0000000001"), dialect()) == Decimal("0.0000000001")
    for value in [0.1, Decimal("NaN"), Decimal("0.00000000001"), Decimal("1e18")]:
        with pytest.raises(ValueError):
            numeric.process_bind_param(value, dialect())
    with pytest.raises(ValueError):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), dialect())
