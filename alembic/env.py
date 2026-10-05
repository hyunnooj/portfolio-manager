from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import Settings
from app.models import Base
from app.models.types import ExactNumeric, UTCDateTime

# A supplied Connection lets integration tests target an isolated schema.
connection = context.config.attributes.get("connection")
url = Settings().database_url.get_secret_value()


def render_type(kind, obj, autogen_context):
    # Future revisions remain independent from the live application's custom types.
    if kind == "type" and isinstance(obj, ExactNumeric):
        return "sa.Numeric(28, 10)"
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def migrate(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        render_item=render_type,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif connection is not None:
    migrate(connection)
else:
    engine = create_engine(
        url,
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC"},
    )
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()
