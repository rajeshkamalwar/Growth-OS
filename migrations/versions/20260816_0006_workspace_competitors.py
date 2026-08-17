"""Add durable workspace competitors.

Revision ID: 20260816_0006
Revises: 20260816_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0006"
down_revision: str | None = "20260816_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_competitors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200",
            name="workspace_competitor_name_length",
        ),
        sa.CheckConstraint("name = btrim(name)", name="workspace_competitor_name_trimmed"),
        sa.CheckConstraint(
            "website_url IS NULL OR char_length(website_url) <= 2048",
            name="workspace_competitor_website_url_length",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR char_length(notes) BETWEEN 1 AND 4000",
            name="workspace_competitor_notes_length",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR notes = btrim(notes)",
            name="workspace_competitor_notes_trimmed",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            name="fk_workspace_competitors_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspace_competitors"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "name",
            name="uq_workspace_competitors_tenant_workspace_name",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_competitors")
