"""SQLAlchemy engine/session setup and schema readiness checks."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util import CommandError
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import PROJECT_ROOT


class Base(DeclarativeBase):
    pass


class SchemaNotMigratedError(RuntimeError):
    """Raised when the database schema is missing or not at the Alembic head."""


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

    def require_current_schema(self) -> None:
        """Verify that Alembic has created and versioned the expected schema.

        This check is intentionally read-only. It never stamps, upgrades,
        deletes, resets, or recreates a database.
        """
        expected = _alembic_head()
        script = _alembic_script()

        if self._sqlite_file_is_missing():
            raise SchemaNotMigratedError(
                "The SQLite database file does not exist; the database has no "
                "application tables and no Alembic version table. Create the "
                "database and run `alembic upgrade head` before starting the "
                "application; automatic database creation and migration are "
                "disabled."
            )

        try:
            connection = self.engine.connect()
        except SQLAlchemyError:
            raise SchemaNotMigratedError(
                "Could not connect to the database to verify the schema. Check "
                "DATABASE_URL and ensure the database is available. No schema "
                "changes were made."
            ) from None

        try:
            with connection:
                tables = set(inspect(connection).get_table_names())
                try:
                    current = MigrationContext.configure(
                        connection
                    ).get_current_revision()
                except CommandError:
                    raise SchemaNotMigratedError(
                        "The alembic_version table contains invalid or conflicting "
                        "revision metadata. Reconcile the database manually; "
                        "automatic stamping and migration are disabled."
                    ) from None
        except SQLAlchemyError:
            raise SchemaNotMigratedError(
                "The database schema could not be inspected. Check database "
                "permissions and schema integrity. No schema changes were made."
            ) from None

        if "alembic_version" not in tables:
            if "jobs" in tables:
                raise SchemaNotMigratedError(
                    "The database has an existing jobs table but no Alembic "
                    "version table. Back up and reconcile the database manually; "
                    "automatic stamping and migration are disabled."
                )
            raise SchemaNotMigratedError(
                "The database has no application tables and no Alembic version "
                "table. Run `alembic upgrade head` before starting the "
                "application; automatic migration is disabled."
            )

        if current is None:
            raise SchemaNotMigratedError(
                "The alembic_version table is empty. Reconcile the database "
                "manually; automatic stamping and migration are disabled."
            )

        if not _revision_is_valid(script, current):
            raise SchemaNotMigratedError(
                f"The alembic_version table contains invalid revision metadata "
                f"{current!r}. Reconcile the database manually; automatic "
                f"stamping and migration are disabled."
            )

        if "jobs" not in tables:
            raise SchemaNotMigratedError(
                f"The database has an Alembic version table at revision "
                f"{current!r} but is missing the jobs table. The schema is "
                f"inconsistent; restore or reconcile it manually."
            )

        if current != expected:
            raise SchemaNotMigratedError(
                f"The database schema revision {current!r} does not match the "
                f"current Alembic head {expected!r}. Run `alembic upgrade head` "
                f"before starting the application; automatic migration is "
                f"disabled."
            )

    def _sqlite_file_is_missing(self) -> bool:
        url = self.engine.url
        if url.get_backend_name() != "sqlite":
            return False

        database = url.database
        if (
            not database
            or database == ":memory:"
            or database.startswith("file:")
            or url.query.get("mode") == "memory"
        ):
            return False

        return not Path(database).exists()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


def _alembic_script() -> ScriptDirectory:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _alembic_head() -> str:
    head = _alembic_script().get_current_head()
    if head is None:
        raise SchemaNotMigratedError("No Alembic head revision is defined.")
    return head


def _revision_is_valid(script: ScriptDirectory, revision: str) -> bool:
    try:
        resolved = script.get_revision(revision)
    except (CommandError, RevisionError):
        return False
    return resolved is not None and resolved.revision == revision
