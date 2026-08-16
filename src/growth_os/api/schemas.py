from datetime import datetime
from typing import TypeVar
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from growth_os.db.models import (
    ApprovalDecisionValue,
    ConnectorStatus,
    MembershipRole,
    ProposalStatus,
    RiskLevel,
)
from growth_os.execution import ExecutionStatus

T = TypeVar("T")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AuditFields(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class Pagination(BaseModel):
    limit: int
    offset: int
    total: int


class Page[T](BaseModel):
    items: list[T]
    pagination: Pagination


class TenantCreate(StrictInput):
    name: str = Field(min_length=1, max_length=200)


class TenantUpdate(StrictInput):
    name: str = Field(min_length=1, max_length=200)


class TenantResponse(AuditFields):
    name: str


class WorkspaceCreate(StrictInput):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceUpdate(StrictInput):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceResponse(AuditFields):
    tenant_id: UUID
    name: str


class MembershipCreate(StrictInput):
    workspace_id: UUID
    user_id: UUID
    role: MembershipRole = MembershipRole.MEMBER


class MembershipUpdate(StrictInput):
    role: MembershipRole


class MembershipResponse(AuditFields):
    tenant_id: UUID
    workspace_id: UUID
    user_id: UUID
    role: MembershipRole


class SiteCreate(StrictInput):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    url: AnyHttpUrl


class SiteUpdate(StrictInput):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: AnyHttpUrl | None = None


class SiteResponse(AuditFields):
    tenant_id: UUID
    workspace_id: UUID
    name: str
    url: str


class ConnectorStatusCreate(StrictInput):
    workspace_id: UUID
    site_id: UUID
    kind: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")


class ConnectorStatusUpdate(StrictInput):
    status: ConnectorStatus


class ConnectorStatusResponse(AuditFields):
    tenant_id: UUID
    workspace_id: UUID
    site_id: UUID
    kind: str
    status: ConnectorStatus


class ExecutionJobCreate(StrictInput):
    workspace_id: UUID
    kind: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    max_attempts: int = Field(default=1, ge=1, le=10)
    retry_delay_seconds: int = Field(default=0, ge=0, le=86400)


class ExecutionRunResponse(AuditFields):
    tenant_id: UUID
    job_id: UUID
    status: ExecutionStatus
    attempt_number: int
    max_attempts: int
    retry_delay_seconds: int
    last_error_code: str | None


class ExecutionJobResponse(AuditFields):
    tenant_id: UUID
    workspace_id: UUID
    kind: str
    idempotency_key: str
    status: ExecutionStatus
    latest_run: ExecutionRunResponse


class ActionProposalCreate(StrictInput):
    job_id: UUID
    action_type: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(min_length=1, max_length=2000)
    risk_level: RiskLevel
    requires_approval: bool

    @model_validator(mode="after")
    def high_risk_requires_approval(self) -> "ActionProposalCreate":
        if self.risk_level is RiskLevel.HIGH and not self.requires_approval:
            raise ValueError("High-risk actions require explicit approval")
        return self


class ActionProposalResponse(AuditFields):
    tenant_id: UUID
    job_id: UUID
    action_type: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool
    status: ProposalStatus


class ApprovalDecisionCreate(StrictInput):
    decision: ApprovalDecisionValue
    decided_by: UUID
    reason: str | None = Field(default=None, max_length=2000)


class ApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    proposal_id: UUID
    decision: ApprovalDecisionValue
    decided_by: UUID
    reason: str | None
    created_at: datetime


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_type: str
    resource_type: str
    resource_id: UUID
    actor_id: UUID | None
    details: dict[str, object]
    created_at: datetime
