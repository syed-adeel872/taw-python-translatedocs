"""SQLAlchemy engine/session setup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Database:
    """Owns the engine and session factory for one application instance."""

    def __init__(self, url: str, echo: bool = False) -> None:
        kwargs: dict = {"echo": echo, "pool_pre_ping": True, "future": True}

        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
            else:
                database_path = url.split("///", 1)[-1]
                if database_path and database_path != ":memory:":
                    Path(database_path).parent.mkdir(parents=True, exist_ok=True)

        self.engine: Engine = create_engine(url, **kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    def create_all(self) -> None:
        from app import models  # noqa: F401  (register mappers)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
