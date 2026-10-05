from datetime import UTC, datetime
from decimal import Decimal, localcontext

from sqlalchemy import DateTime, Numeric
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class ExactNumeric(TypeDecorator[Decimal]):
    """Reject binary floats and silent PostgreSQL NUMERIC rounding."""

    impl = Numeric(28, 10)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("Financial amounts require a finite Decimal")
        with localcontext() as context:
            context.prec = 40
            if abs(value) >= Decimal("1e18") or value != value.quantize(Decimal("1e-10")):
                raise ValueError("Amount exceeds NUMERIC(28,10) precision")
        return value


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware datetime required")
        return value.astimezone(UTC)
