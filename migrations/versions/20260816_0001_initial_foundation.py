"""Create the initial multi-tenant foundation tables.

Revision ID: 20260816_0001
Revises: None
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_table(
        "workspaces",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_workspaces_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("id", "tenant_id", name="uq_workspaces_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_workspaces_tenant_id_name"),
    )
    op.create_index(op.f("ix_workspaces_tenant_id"), "workspaces", ["tenant_id"])
    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "OWNER",
                "ADMIN",
                "MEMBER",
                "VIEWER",
                name="membershiprole",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            name="fk_memberships_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint(
            "tenant_id", "workspace_id", "user_id", name="uq_memberships_workspace_user"
        ),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"])
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_table(
        "sites",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            name="fk_sites_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
        sa.UniqueConstraint("id", "workspace_id", "tenant_id", name="uq_sites_id_workspace_tenant"),
        sa.UniqueConstraint("tenant_id", "workspace_id", "url", name="uq_sites_workspace_url"),
    )
    op.create_index(op.f("ix_sites_tenant_id"), "sites", ["tenant_id"])
    op.create_table(
        "connectors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NOT_CONFIGURED",
                "CONNECTED",
                "DEGRADED",
                "DISCONNECTED",
                name="connectorstatus",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["site_id", "workspace_id", "tenant_id"],
            ["sites.id", "sites.workspace_id", "sites.tenant_id"],
            name="fk_connectors_site_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connectors")),
        sa.UniqueConstraint(
            "tenant_id", "workspace_id", "site_id", "kind", name="uq_connectors_site_kind"
        ),
    )
    op.create_index(op.f("ix_connectors_tenant_id"), "connectors", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_connectors_tenant_id"), table_name="connectors")
    op.drop_table("connectors")
    op.drop_index(op.f("ix_sites_tenant_id"), table_name="sites")
    op.drop_table("sites")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_tenant_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_workspaces_tenant_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("tenants")
