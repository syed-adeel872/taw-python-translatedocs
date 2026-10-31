"""Create jobs table.

Revision ID: 0001
Revises:
Create Date: 2026-10-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("source_language", sa.String(length=20), nullable=False),
        sa.Column("target_language", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_path", sa.String(length=255), nullable=True),
        sa.Column("output_path", sa.String(length=255), nullable=True),
        sa.Column("output_filename", sa.String(length=255), nullable=True),
        sa.Column("characters_translated", sa.Integer(), nullable=False),
        sa.Column("segments_translated", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
