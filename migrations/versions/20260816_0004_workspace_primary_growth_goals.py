"""Add tenant-safe workspace primary growth goals.

Revision ID: 20260816_0004
Revises: 20260816_0003
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0004"
down_revision: str | None = "20260816_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_primary_growth_goals",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("objective", sa.String(length=2000), nullable=False),
        sa.Column("success_definition", sa.String(length=2000), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            name="fk_workspace_primary_growth_goals_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_primary_growth_goals")),
        sa.UniqueConstraint(
            "tenant_id", "workspace_id", name="uq_workspace_primary_growth_goals_tenant_workspace"
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_primary_growth_goals")
