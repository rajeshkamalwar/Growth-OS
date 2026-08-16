"""Add tenant-safe workspace business profiles.

Revision ID: 20260816_0003
Revises: 20260816_0002
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0003"
down_revision: str | None = "20260816_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_business_profiles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("business_description", sa.String(length=4000), nullable=True),
        sa.Column("products_services", sa.String(length=4000), nullable=True),
        sa.Column("target_audience", sa.String(length=4000), nullable=True),
        sa.Column("positioning", sa.String(length=4000), nullable=True),
        sa.Column("brand_voice", sa.String(length=4000), nullable=True),
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
            name="fk_workspace_business_profiles_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_business_profiles")),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            name="uq_workspace_business_profiles_tenant_workspace",
        ),
    )
    op.create_index(
        op.f("ix_workspace_business_profiles_tenant_id"),
        "workspace_business_profiles",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workspace_business_profiles_tenant_id"),
        table_name="workspace_business_profiles",
    )
    op.drop_table("workspace_business_profiles")
