from dataclasses import dataclass
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from growth_os.db.base import Base
from growth_os.db.models import (
    Connector,
    Membership,
    Site,
    Tenant,
    Workspace,
    WorkspaceAutonomyPolicy,
    WorkspaceBusinessProfile,
    WorkspaceCompetitor,
    WorkspacePrimaryGrowthGoal,
)

TenantOwned = TypeVar("TenantOwned", Workspace, Membership, Site, Connector)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID


@dataclass(frozen=True)
class OnboardingRecordStatus:
    has_site: bool
    has_business_profile: bool
    has_primary_growth_goal: bool
    has_autonomy_policy: bool


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

    async def get_primary_growth_goal(
        self, context: TenantContext, workspace_id: UUID
    ) -> WorkspacePrimaryGrowthGoal | None:
        return cast(
            WorkspacePrimaryGrowthGoal | None,
            await self.session.scalar(
                select(WorkspacePrimaryGrowthGoal).where(
                    WorkspacePrimaryGrowthGoal.tenant_id == context.tenant_id,
                    WorkspacePrimaryGrowthGoal.workspace_id == workspace_id,
                )
            ),
        )

    async def get_autonomy_policy(
        self, context: TenantContext, workspace_id: UUID
    ) -> WorkspaceAutonomyPolicy | None:
        return cast(
            WorkspaceAutonomyPolicy | None,
            await self.session.scalar(
                select(WorkspaceAutonomyPolicy).where(
                    WorkspaceAutonomyPolicy.tenant_id == context.tenant_id,
                    WorkspaceAutonomyPolicy.workspace_id == workspace_id,
                )
            ),
        )

    async def get_competitor(
        self, context: TenantContext, workspace_id: UUID, competitor_id: UUID
    ) -> WorkspaceCompetitor | None:
        return cast(
            WorkspaceCompetitor | None,
            await self.session.scalar(
                select(WorkspaceCompetitor).where(
                    WorkspaceCompetitor.tenant_id == context.tenant_id,
                    WorkspaceCompetitor.workspace_id == workspace_id,
                    WorkspaceCompetitor.id == competitor_id,
                )
            ),
        )

    async def list_competitors(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[WorkspaceCompetitor], int]:
        predicate = (
            WorkspaceCompetitor.tenant_id == context.tenant_id,
            WorkspaceCompetitor.workspace_id == workspace_id,
        )
        items = list(
            (
                await self.session.scalars(
                    select(WorkspaceCompetitor)
                    .where(*predicate)
                    .order_by(WorkspaceCompetitor.created_at, WorkspaceCompetitor.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(WorkspaceCompetitor).where(*predicate)
        )
        return items, total or 0

    async def get_onboarding_record_status(
        self, context: TenantContext, workspace_id: UUID
    ) -> OnboardingRecordStatus:
        row = (
            await self.session.execute(
                select(
                    exists()
                    .where(
                        Site.tenant_id == context.tenant_id,
                        Site.workspace_id == workspace_id,
                    )
                    .label("has_site"),
                    exists()
                    .where(
                        WorkspaceBusinessProfile.tenant_id == context.tenant_id,
                        WorkspaceBusinessProfile.workspace_id == workspace_id,
                    )
                    .label("has_business_profile"),
                    exists()
                    .where(
                        WorkspacePrimaryGrowthGoal.tenant_id == context.tenant_id,
                        WorkspacePrimaryGrowthGoal.workspace_id == workspace_id,
                    )
                    .label("has_primary_growth_goal"),
                    exists()
                    .where(
                        WorkspaceAutonomyPolicy.tenant_id == context.tenant_id,
                        WorkspaceAutonomyPolicy.workspace_id == workspace_id,
                    )
                    .label("has_autonomy_policy"),
                )
            )
        ).one()
        return OnboardingRecordStatus(
            has_site=bool(row.has_site),
            has_business_profile=bool(row.has_business_profile),
            has_primary_growth_goal=bool(row.has_primary_growth_goal),
            has_autonomy_policy=bool(row.has_autonomy_policy),
        )

    async def flush(self) -> None:
        await self.session.flush()

    async def refresh(self, entity: Any) -> None:
        await self.session.refresh(entity)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
