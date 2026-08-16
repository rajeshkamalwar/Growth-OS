from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from growth_os.db.base import Base, UUIDTimestampMixin
from growth_os.execution import ExecutionStatus


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ConnectorStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProposalStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecisionValue(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class Tenant(UUIDTimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Workspace(UUIDTimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_workspaces_id_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_workspaces_tenant_id_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class WorkspaceBusinessProfile(UUIDTimestampMixin, Base):
    __tablename__ = "workspace_business_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_workspace_business_profiles_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            name="uq_workspace_business_profiles_tenant_workspace",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    products_services: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    target_audience: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    positioning: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    brand_voice: Mapped[str | None] = mapped_column(String(4000), nullable=True)


class Membership(UUIDTimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_memberships_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "user_id",
            name="uq_memberships_workspace_user",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, native_enum=False, length=20),
        default=MembershipRole.MEMBER,
        nullable=False,
    )


class Site(UUIDTimestampMixin, Base):
    __tablename__ = "sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_sites_workspace_tenant",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "tenant_id",
            name="uq_sites_id_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "url",
            name="uq_sites_workspace_url",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)


class Connector(UUIDTimestampMixin, Base):
    """Persistence placeholder for future connector implementations."""

    __tablename__ = "connectors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "workspace_id", "tenant_id"],
            ["sites.id", "sites.workspace_id", "sites.tenant_id"],
            ondelete="RESTRICT",
            name="fk_connectors_site_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "site_id",
            "kind",
            name="uq_connectors_site_kind",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    site_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ConnectorStatus] = mapped_column(
        Enum(ConnectorStatus, native_enum=False, length=30),
        default=ConnectorStatus.NOT_CONFIGURED,
        nullable=False,
    )


class ExecutionJob(UUIDTimestampMixin, Base):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_execution_jobs_workspace_tenant",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_execution_jobs_id_tenant_id"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_execution_jobs_tenant_idempotency"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, native_enum=False, length=30),
        default=ExecutionStatus.QUEUED,
        nullable=False,
    )


class ExecutionRun(UUIDTimestampMixin, Base):
    __tablename__ = "execution_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["execution_jobs.id", "execution_jobs.tenant_id"],
            ondelete="RESTRICT",
            name="fk_execution_runs_job_tenant",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_execution_runs_id_tenant_id"),
        UniqueConstraint("tenant_id", "job_id", "attempt_number", name="uq_runs_job_attempt"),
        CheckConstraint("attempt_number >= 1", name="attempt_positive"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="max_attempts"),
        CheckConstraint("attempt_number <= max_attempts", name="attempt_within_max"),
        CheckConstraint("retry_delay_seconds BETWEEN 0 AND 86400", name="retry_delay"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    job_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, native_enum=False, length=30),
        default=ExecutionStatus.QUEUED,
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ActionProposal(UUIDTimestampMixin, Base):
    __tablename__ = "action_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["execution_jobs.id", "execution_jobs.tenant_id"],
            ondelete="RESTRICT",
            name="fk_action_proposals_job_tenant",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_action_proposals_id_tenant_id"),
        CheckConstraint(
            "risk_level != 'HIGH' OR requires_approval",
            name="high_risk_requires_approval",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    job_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, native_enum=False, length=20), nullable=False
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, native_enum=False, length=30),
        default=ProposalStatus.AWAITING_APPROVAL,
        nullable=False,
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["proposal_id", "tenant_id"],
            ["action_proposals.id", "action_proposals.tenant_id"],
            ondelete="RESTRICT",
            name="fk_approval_decisions_proposal_tenant",
        ),
        UniqueConstraint("tenant_id", "proposal_id", name="uq_decisions_final_proposal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    proposal_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    decision: Mapped[ApprovalDecisionValue] = mapped_column(
        Enum(ApprovalDecisionValue, native_enum=False, length=20), nullable=False
    )
    decided_by: Mapped[UUID] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
