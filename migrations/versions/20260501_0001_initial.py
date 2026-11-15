"""Initial schema: users, links and clicks.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-01 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial tables and indexes."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_links_code", "links", ["code"], unique=True)
    op.create_index("ix_links_user_id", "links", ["user_id"], unique=False)
    op.create_index("ix_links_user_created", "links", ["user_id", "created_at"], unique=False)

    op.create_table(
        "clicks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("link_id", sa.Integer(), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("referer", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("device_type", sa.String(length=16), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["links.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_clicks_link_id", "clicks", ["link_id"], unique=False)
    op.create_index("ix_clicks_clicked_at", "clicks", ["clicked_at"], unique=False)
    op.create_index("ix_clicks_link_clicked", "clicks", ["link_id", "clicked_at"], unique=False)


def downgrade() -> None:
    """Drop every table created by this revision."""
    op.drop_index("ix_clicks_link_clicked", table_name="clicks")
    op.drop_index("ix_clicks_clicked_at", table_name="clicks")
    op.drop_index("ix_clicks_link_id", table_name="clicks")
    op.drop_table("clicks")

    op.drop_index("ix_links_user_created", table_name="links")
    op.drop_index("ix_links_user_id", table_name="links")
    op.drop_index("ix_links_code", table_name="links")
    op.drop_table("links")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
