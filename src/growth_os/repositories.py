from dataclasses import dataclass
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from growth_os.db.base import Base
from growth_os.db.models import (
    Connector,
    Membership,
    Site,
    Tenant,
    Workspace,
    WorkspaceBusinessProfile,
)

TenantOwned = TypeVar("TenantOwned", Workspace, Membership, Site, Connector)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID


class FoundationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, entity: Base) -> None:
        self.session.add(entity)

    async def get_tenant(self, context: TenantContext) -> Tenant | None:
        return cast(
            Tenant | None,
            await self.session.scalar(select(Tenant).where(Tenant.id == context.tenant_id)),
        )

    async def get_owned(
        self, model: type[TenantOwned], context: TenantContext, resource_id: UUID
    ) -> TenantOwned | None:
        return cast(
            TenantOwned | None,
            await self.session.scalar(
                select(model).where(model.id == resource_id, model.tenant_id == context.tenant_id)
            ),
        )

    async def list_owned(
        self,
        model: type[TenantOwned],
        context: TenantContext,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[TenantOwned], int]:
        predicate = model.tenant_id == context.tenant_id
        items = list(
            (
                await self.session.scalars(
                    select(model)
                    .where(predicate)
                    .order_by(model.created_at, model.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = await self.session.scalar(select(func.count()).select_from(model).where(predicate))
        return items, total or 0

    async def get_business_profile(
        self, context: TenantContext, workspace_id: UUID
    ) -> WorkspaceBusinessProfile | None:
        return cast(
            WorkspaceBusinessProfile | None,
            await self.session.scalar(
                select(WorkspaceBusinessProfile).where(
                    WorkspaceBusinessProfile.tenant_id == context.tenant_id,
                    WorkspaceBusinessProfile.workspace_id == workspace_id,
                )
            ),
        )

    async def flush(self) -> None:
        await self.session.flush()

    async def refresh(self, entity: Any) -> None:
        await self.session.refresh(entity)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
