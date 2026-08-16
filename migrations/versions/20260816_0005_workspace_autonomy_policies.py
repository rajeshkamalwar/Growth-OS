"""Add durable workspace autonomy policies.

Revision ID: 20260816_0005
Revises: 20260816_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0005"
down_revision: str | None = "20260816_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_autonomy_policies",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "level",
            sa.Enum(
                "observe_only",
                "recommend_only",
                "approval_required",
                "low_risk_auto",
                name="autonomy_level",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("is_paused", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            name="fk_workspace_autonomy_policies_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspace_autonomy_policies"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            name="uq_workspace_autonomy_policies_tenant_workspace",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_autonomy_policies")
