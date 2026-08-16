from datetime import datetime
from typing import TypeVar
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from growth_os.db.models import ConnectorStatus, MembershipRole

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
