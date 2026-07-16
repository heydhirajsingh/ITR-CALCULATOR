"""SQLite engine and session management."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.database.base import Base

settings = get_settings()


def _database_url() -> str:
    # SQLCipher support is optional and deliberately activated only when a key is supplied.
    if settings.db_key:
        try:
            import pysqlcipher3  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "ITR_DB_KEY is set, but pysqlcipher3/SQLCipher is not installed. "
                "Install requirements-optional.txt or unset ITR_DB_KEY."
            ) from exc
        return f"sqlite+pysqlcipher://:{settings.db_key}@/{settings.database_path.as_posix()}"
    return f"sqlite:///{settings.database_path.as_posix()}"


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_db() -> None:
    # Import models so metadata is populated.
    from backend.app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
