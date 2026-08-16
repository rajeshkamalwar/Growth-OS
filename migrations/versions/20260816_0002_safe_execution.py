"""Add tenant-safe execution, approval, and audit entities.

Revision ID: 20260816_0002
Revises: 20260816_0001
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0002"
down_revision: str | None = "20260816_0001"
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
        "execution_jobs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "AWAITING_APPROVAL",
                "APPROVED",
                "REJECTED",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                name="executionstatus",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            name="fk_execution_jobs_workspace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_jobs")),
        sa.UniqueConstraint("id", "tenant_id", name="uq_execution_jobs_id_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_execution_jobs_tenant_idempotency"
        ),
    )
    op.create_index(op.f("ix_execution_jobs_tenant_id"), "execution_jobs", ["tenant_id"])

    op.create_table(
        "execution_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "AWAITING_APPROVAL",
                "APPROVED",
                "REJECTED",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                name="executionstatus",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("attempt_number >= 1", name="ck_execution_runs_attempt_positive"),
        sa.CheckConstraint(
            "attempt_number <= max_attempts", name="ck_execution_runs_attempt_within_max"
        ),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_execution_runs_max_attempts"),
        sa.CheckConstraint(
            "retry_delay_seconds BETWEEN 0 AND 86400",
            name="ck_execution_runs_retry_delay",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["execution_jobs.id", "execution_jobs.tenant_id"],
            name="fk_execution_runs_job_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_runs")),
        sa.UniqueConstraint("id", "tenant_id", name="uq_execution_runs_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "job_id", "attempt_number", name="uq_runs_job_attempt"),
    )
    op.create_index(op.f("ix_execution_runs_job_id"), "execution_runs", ["job_id"])
    op.create_index(op.f("ix_execution_runs_tenant_id"), "execution_runs", ["tenant_id"])

    op.create_table(
        "action_proposals",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column(
            "risk_level",
            sa.Enum("READ_ONLY", "LOW", "MEDIUM", "HIGH", name="risklevel", native_enum=False),
            nullable=False,
        ),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "AWAITING_APPROVAL",
                "APPROVED",
                "REJECTED",
                name="proposalstatus",
                native_enum=False,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "risk_level != 'HIGH' OR requires_approval",
            name="ck_action_proposals_high_risk_requires_approval",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["execution_jobs.id", "execution_jobs.tenant_id"],
            name="fk_action_proposals_job_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_proposals")),
        sa.UniqueConstraint("id", "tenant_id", name="uq_action_proposals_id_tenant_id"),
    )
    op.create_index(op.f("ix_action_proposals_job_id"), "action_proposals", ["job_id"])
    op.create_index(op.f("ix_action_proposals_tenant_id"), "action_proposals", ["tenant_id"])

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "APPROVED",
                "REJECTED",
                name="approvaldecisionvalue",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id", "tenant_id"],
            ["action_proposals.id", "action_proposals.tenant_id"],
            name="fk_approval_decisions_proposal_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decisions")),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_decisions_final_proposal"),
    )
    op.create_index(
        op.f("ix_approval_decisions_proposal_id"), "approval_decisions", ["proposal_id"]
    )
    op.create_index(op.f("ix_approval_decisions_tenant_id"), "approval_decisions", ["tenant_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_resource_id"), "audit_events", ["resource_id"])
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_tenant_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_resource_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_approval_decisions_tenant_id"), table_name="approval_decisions")
    op.drop_index(op.f("ix_approval_decisions_proposal_id"), table_name="approval_decisions")
    op.drop_table("approval_decisions")
    op.drop_index(op.f("ix_action_proposals_tenant_id"), table_name="action_proposals")
    op.drop_index(op.f("ix_action_proposals_job_id"), table_name="action_proposals")
    op.drop_table("action_proposals")
    op.drop_index(op.f("ix_execution_runs_tenant_id"), table_name="execution_runs")
    op.drop_index(op.f("ix_execution_runs_job_id"), table_name="execution_runs")
    op.drop_table("execution_runs")
    op.drop_index(op.f("ix_execution_jobs_tenant_id"), table_name="execution_jobs")
    op.drop_table("execution_jobs")
