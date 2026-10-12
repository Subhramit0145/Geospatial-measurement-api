import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from app.config import settings

logger = logging.getLogger(__name__)


def _create_database_engine():
    """
    Construct an enterprise-tuned SQLAlchemy Engine.
    Configures SQLite with WAL mode and high busy-timeout for concurrent readers/writers,
    or attaches a tuned QueuePool with pre-ping and connection recycling for PostgreSQL.
    """
    url = settings.database_url

    if url.startswith("sqlite"):
        is_memory = ":memory:" in url
        connect_args = {
            "check_same_thread": False,
            "timeout": 30.0,  # Wait up to 30 seconds before timing out on locks
        }

        if is_memory:
            return create_engine(
                url,
                connect_args=connect_args,
                poolclass=StaticPool,
            )

        eng = create_engine(
            url,
            connect_args=connect_args,
        )

        # Optimize SQLite for high concurrency through Write-Ahead Logging (WAL)
        @event.listens_for(eng, "connect")
        def set_sqlite_concurrency_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")
                cursor.execute("PRAGMA cache_size=-64000;")  # 64MB memory cache
                cursor.execute("PRAGMA temp_store=MEMORY;")
            except Exception as e:
                logger.debug("Failed setting SQLite pragma: %s", e)
            finally:
                cursor.close()

        return eng

    # Enterprise RDBMS (PostgreSQL, MySQL, etc.) with high-concurrency pooling
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
    )


engine = _create_database_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_pool_status() -> dict:
    """Telemetry report of active database connection pool status."""
    pool = getattr(engine, "pool", None)
    if pool is None:
        return {"type": "unknown"}

    if isinstance(pool, QueuePool):
        return {
            "type": "QueuePool",
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    return {
        "type": pool.__class__.__name__,
        "status": "active",
    }

