from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app import database as database_module
from app import models  # noqa: F401
from app.config import PROJECT_ROOT, Settings
from app.database import Base, Database, SchemaNotMigratedError
from app.main import create_app
from tests.helpers import run_migrations

EXPECTED_REVISION = "0001"
VERSION_TABLE_DDL = """
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
)
"""


def _sqlite_path(settings: Settings) -> Path:
    return Path(settings.database_url.removeprefix("sqlite:///"))


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def _version_values(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT version_num FROM alembic_version")
        ]


def _create_jobs_schema(settings: Settings) -> None:
    database = Database(settings.database_url)
    try:
        Base.metadata.create_all(database.engine)
    finally:
        database.dispose()


def _create_version_table(path: Path, *revisions: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(VERSION_TABLE_DDL)
        connection.executemany(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            [(revision,) for revision in revisions],
        )


def test_alembic_migration_creates_expected_schema(settings):
    run_migrations(settings.database_url)

    database = Database(settings.database_url)
    try:
        inspector = inspect(database.engine)
        assert {"alembic_version", "jobs"} <= set(inspector.get_table_names())

        indexes = {index["name"] for index in inspector.get_indexes("jobs")}
        assert {"ix_jobs_status", "ix_jobs_created_at"} <= indexes

        with database.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == EXPECTED_REVISION
    finally:
        database.dispose()


@pytest.mark.parametrize("url_suffix", ["", "?mode=rwc&uri=true"])
def test_startup_does_not_create_missing_sqlite_database(settings, url_suffix):
    path = _sqlite_path(settings)
    settings.database_url = f"{settings.database_url}{url_suffix}"
    assert not path.exists()

    app = create_app(settings)
    with pytest.raises(
        SchemaNotMigratedError,
        match="SQLite database file does not exist",
    ):
        with TestClient(app):
            pass

    assert not path.exists()


def test_startup_rejects_unversioned_jobs_table(settings):
    _create_jobs_schema(settings)

    path = _sqlite_path(settings)
    assert "jobs" in _tables(path)
    assert "alembic_version" not in _tables(path)

    app = create_app(settings)
    with pytest.raises(
        SchemaNotMigratedError,
        match="existing jobs table but no Alembic version table",
    ):
        with TestClient(app):
            pass

    assert "alembic_version" not in _tables(path)


def test_startup_rejects_empty_revision_metadata(settings):
    path = _sqlite_path(settings)
    _create_version_table(path)

    app = create_app(settings)
    with pytest.raises(SchemaNotMigratedError, match="alembic_version table is empty"):
        with TestClient(app):
            pass

    assert _version_values(path) == []


@pytest.mark.parametrize(
    "revision", ["not-a-real-revision", "head", "base", "0", "000"]
)
def test_startup_rejects_invalid_revision_metadata(settings, revision):
    path = _sqlite_path(settings)
    _create_version_table(path, revision)

    app = create_app(settings)
    with pytest.raises(
        SchemaNotMigratedError,
        match=f"invalid revision metadata '{revision}'",
    ):
        with TestClient(app):
            pass

    assert _version_values(path) == [revision]


def test_startup_rejects_conflicting_revision_metadata(settings):
    path = _sqlite_path(settings)
    _create_version_table(path, EXPECTED_REVISION, "0002")

    app = create_app(settings)
    with pytest.raises(
        SchemaNotMigratedError,
        match="invalid or conflicting revision metadata",
    ):
        with TestClient(app):
            pass

    assert _version_values(path) == [EXPECTED_REVISION, "0002"]


def test_startup_rejects_revision_that_does_not_match_head(settings, monkeypatch):
    run_migrations(settings.database_url)
    monkeypatch.setattr(database_module, "_alembic_head", lambda: "0002")

    app = create_app(settings)
    with pytest.raises(
        SchemaNotMigratedError,
        match="revision '0001' does not match the current Alembic head '0002'",
    ):
        with TestClient(app):
            pass

    assert _version_values(_sqlite_path(settings)) == [EXPECTED_REVISION]


def test_startup_rejects_version_table_without_jobs_table(settings):
    path = _sqlite_path(settings)
    _create_version_table(path, EXPECTED_REVISION)

    app = create_app(settings)
    with pytest.raises(SchemaNotMigratedError, match="missing the jobs table"):
        with TestClient(app):
            pass

    assert "jobs" not in _tables(path)
    assert _version_values(path) == [EXPECTED_REVISION]


def test_startup_reports_database_connection_failures(settings, tmp_path):
    settings.database_url = f"sqlite:///{tmp_path.as_posix()}"

    app = create_app(settings)
    with pytest.raises(
        SchemaNotMigratedError,
        match="Could not connect to the database to verify the schema",
    ):
        with TestClient(app):
            pass


def test_startup_accepts_migrated_database(settings, monkeypatch):
    run_migrations(settings.database_url)
    schema_checks = []
    original_check = Database.require_current_schema

    def record_schema_check(database):
        schema_checks.append(database)
        original_check(database)

    monkeypatch.setattr(Database, "require_current_schema", record_schema_check)
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert schema_checks


def test_run_migrations_rejects_target_outside_temporary_directory():
    target = PROJECT_ROOT / "instance" / f"guard-{uuid.uuid4().hex}.db"

    with pytest.raises(ValueError, match="outside the system temporary directory"):
        run_migrations(f"sqlite:///{target.as_posix()}")

    assert not target.exists()


def test_run_migrations_rejects_relative_sqlite_target():
    with pytest.raises(ValueError, match="must be an absolute path"):
        run_migrations("sqlite:///instance/guard-relative.db")


def test_run_migrations_rejects_non_sqlite_target_without_echoing_secret():
    secret = "do-not-expose-this-password"
    url = f"postgresql+psycopg://user:{secret}@127.0.0.1:1/translatedocs_test"

    with pytest.raises(ValueError, match="only target isolated SQLite") as exc_info:
        run_migrations(url)

    assert secret not in str(exc_info.value)
