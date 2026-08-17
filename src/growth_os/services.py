from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from growth_os.api.errors import ConflictError, NotFoundError
from growth_os.api.schemas import OnboardingStatusResponse, OnboardingStep
from growth_os.db.models import (
    AuditEvent,
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
from growth_os.repositories import FoundationRepository, TenantContext

Entity = TypeVar("Entity", Tenant, Workspace, Membership, Site, Connector)
OwnedEntity = TypeVar("OwnedEntity", Workspace, Membership, Site, Connector)


class FoundationService:
    def __init__(self, repository: FoundationRepository) -> None:
        self.repository = repository

    async def create_tenant(self, *, name: str) -> Tenant:
        return await self._persist(Tenant(name=name))

    async def get_onboarding_status(
        self, context: TenantContext, workspace_id: UUID
    ) -> OnboardingStatusResponse:
        await self.get_owned(Workspace, context, workspace_id)
        status = await self.repository.get_onboarding_record_status(context, workspace_id)
        ordered_steps = (
            (OnboardingStep.SITE, status.has_site),
            (OnboardingStep.BUSINESS_PROFILE, status.has_business_profile),
            (OnboardingStep.PRIMARY_GROWTH_GOAL, status.has_primary_growth_goal),
            (OnboardingStep.AUTONOMY_POLICY, status.has_autonomy_policy),
        )
        flags = tuple(present for _, present in ordered_steps)
        return OnboardingStatusResponse(
            tenant_id=context.tenant_id,
            workspace_id=workspace_id,
            has_site=status.has_site,
            has_business_profile=status.has_business_profile,
            has_primary_growth_goal=status.has_primary_growth_goal,
            has_autonomy_policy=status.has_autonomy_policy,
            is_foundation_complete=all(flags),
            missing_steps=[step for step, present in ordered_steps if not present],
        )

    async def get_tenant(self, context: TenantContext) -> Tenant:
        tenant = await self.repository.get_tenant(context)
        if tenant is None:
            raise NotFoundError
        return tenant

    async def update_tenant(self, context: TenantContext, *, name: str) -> Tenant:
        tenant = await self.get_tenant(context)
        tenant.name = name
        return await self._persist(tenant)

    async def create_workspace(self, context: TenantContext, *, name: str) -> Workspace:
        await self.get_tenant(context)
        return await self._persist(Workspace(tenant_id=context.tenant_id, name=name))

    async def create_membership(
        self, context: TenantContext, *, workspace_id: UUID, user_id: UUID, role: Any
    ) -> Membership:
        await self.get_owned(Workspace, context, workspace_id)
        return await self._persist(
            Membership(
                tenant_id=context.tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
            )
        )

    async def create_site(
        self, context: TenantContext, *, workspace_id: UUID, name: str, url: str
    ) -> Site:
        await self.get_owned(Workspace, context, workspace_id)
        return await self._persist(
            Site(
                tenant_id=context.tenant_id,
                workspace_id=workspace_id,
                name=name,
                url=url,
            )
        )

    async def create_connector(
        self,
        context: TenantContext,
        *,
        workspace_id: UUID,
        site_id: UUID,
        kind: str,
    ) -> Connector:
        site = await self.get_owned(Site, context, site_id)
        if site.workspace_id != workspace_id:
            raise NotFoundError
        return await self._persist(
            Connector(
                tenant_id=context.tenant_id,
                workspace_id=workspace_id,
                site_id=site_id,
                kind=kind,
            )
        )

    async def get_owned(
        self, model: type[OwnedEntity], context: TenantContext, resource_id: UUID
    ) -> OwnedEntity:
        entity = await self.repository.get_owned(model, context, resource_id)
        if entity is None:
            raise NotFoundError
        return entity

    async def list_owned(
        self,
        model: type[OwnedEntity],
        context: TenantContext,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[OwnedEntity], int]:
        await self.get_tenant(context)
        return await self.repository.list_owned(model, context, limit=limit, offset=offset)

    async def update_owned(
        self,
        model: type[OwnedEntity],
        context: TenantContext,
        resource_id: UUID,
        changes: Mapping[str, Any],
    ) -> OwnedEntity:
        entity = await self.get_owned(model, context, resource_id)
        for field, value in changes.items():
            setattr(entity, field, value)
        return await self._persist(entity)

    async def create_business_profile(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        values: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspaceBusinessProfile:
        await self.get_owned(Workspace, context, workspace_id)
        profile = WorkspaceBusinessProfile(
            tenant_id=context.tenant_id, workspace_id=workspace_id, **values
        )
        audit = self._profile_audit(
            profile,
            "workspace_business_profile.created",
            sorted(values),
            actor_id,
        )
        self.repository.add(profile)
        self.repository.add(audit)
        return await self._persist_profile(profile)

    async def get_business_profile(
        self, context: TenantContext, workspace_id: UUID
    ) -> WorkspaceBusinessProfile:
        await self.get_owned(Workspace, context, workspace_id)
        profile = await self.repository.get_business_profile(context, workspace_id)
        if profile is None:
            raise NotFoundError
        return profile

    async def update_business_profile(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        changes: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspaceBusinessProfile:
        profile = await self.get_business_profile(context, workspace_id)
        for field, value in changes.items():
            setattr(profile, field, value)
        self.repository.add(
            self._profile_audit(
                profile,
                "workspace_business_profile.updated",
                sorted(changes),
                actor_id,
            )
        )
        return await self._persist_profile(profile)

    async def create_primary_growth_goal(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        values: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspacePrimaryGrowthGoal:
        await self.get_owned(Workspace, context, workspace_id)
        goal = WorkspacePrimaryGrowthGoal(
            tenant_id=context.tenant_id, workspace_id=workspace_id, **values
        )
        self.repository.add(goal)
        self.repository.add(
            self._goal_audit(
                goal, "workspace_primary_growth_goal.created", sorted(values), actor_id
            )
        )
        return await self._persist_goal(goal)

    async def get_primary_growth_goal(
        self, context: TenantContext, workspace_id: UUID
    ) -> WorkspacePrimaryGrowthGoal:
        await self.get_owned(Workspace, context, workspace_id)
        goal = await self.repository.get_primary_growth_goal(context, workspace_id)
        if goal is None:
            raise NotFoundError
        return goal

    async def update_primary_growth_goal(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        changes: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspacePrimaryGrowthGoal:
        goal = await self.get_primary_growth_goal(context, workspace_id)
        for field, value in changes.items():
            setattr(goal, field, value)
        self.repository.add(
            self._goal_audit(
                goal, "workspace_primary_growth_goal.updated", sorted(changes), actor_id
            )
        )
        return await self._persist_goal(goal)

    async def create_autonomy_policy(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        values: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspaceAutonomyPolicy:
        await self.get_owned(Workspace, context, workspace_id)
        policy = WorkspaceAutonomyPolicy(
            tenant_id=context.tenant_id, workspace_id=workspace_id, **values
        )
        self.repository.add(policy)
        self.repository.add(
            self._autonomy_policy_audit(
                policy, "workspace_autonomy_policy.created", sorted(values), actor_id
            )
        )
        return await self._persist_autonomy_policy(policy)

    async def get_autonomy_policy(
        self, context: TenantContext, workspace_id: UUID
    ) -> WorkspaceAutonomyPolicy:
        await self.get_owned(Workspace, context, workspace_id)
        policy = await self.repository.get_autonomy_policy(context, workspace_id)
        if policy is None:
            raise NotFoundError
        return policy

    async def update_autonomy_policy(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        changes: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspaceAutonomyPolicy:
        policy = await self.get_autonomy_policy(context, workspace_id)
        for field, value in changes.items():
            setattr(policy, field, value)
        self.repository.add(
            self._autonomy_policy_audit(
                policy, "workspace_autonomy_policy.updated", sorted(changes), actor_id
            )
        )
        return await self._persist_autonomy_policy(policy)

    async def create_competitor(
        self,
        context: TenantContext,
        workspace_id: UUID,
        *,
        values: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspaceCompetitor:
        await self.get_owned(Workspace, context, workspace_id)
        competitor = WorkspaceCompetitor(
            tenant_id=context.tenant_id, workspace_id=workspace_id, **values
        )
        try:
            self.repository.add(competitor)
            await self.repository.flush()
            self.repository.add(
                self._competitor_audit(
                    competitor, "workspace_competitor.created", sorted(values), actor_id
                )
            )
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        except Exception:
            await self.repository.rollback()
            raise
        await self.repository.refresh(competitor)
        return competitor

    async def list_competitors(
        self, context: TenantContext, workspace_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[WorkspaceCompetitor], int]:
        await self.get_owned(Workspace, context, workspace_id)
        return await self.repository.list_competitors(
            context, workspace_id, limit=limit, offset=offset
        )

    async def get_competitor(
        self, context: TenantContext, workspace_id: UUID, competitor_id: UUID
    ) -> WorkspaceCompetitor:
        await self.get_owned(Workspace, context, workspace_id)
        competitor = await self.repository.get_competitor(context, workspace_id, competitor_id)
        if competitor is None:
            raise NotFoundError
        return competitor

    async def update_competitor(
        self,
        context: TenantContext,
        workspace_id: UUID,
        competitor_id: UUID,
        *,
        changes: Mapping[str, Any],
        actor_id: UUID | None,
    ) -> WorkspaceCompetitor:
        competitor = await self.get_competitor(context, workspace_id, competitor_id)
        for field, value in changes.items():
            setattr(competitor, field, value)
        self.repository.add(
            self._competitor_audit(
                competitor, "workspace_competitor.updated", sorted(changes), actor_id
            )
        )
        return await self._persist_competitor(competitor)

    @staticmethod
    def _competitor_audit(
        competitor: WorkspaceCompetitor,
        event_type: str,
        changed_fields: list[str],
        actor_id: UUID | None,
    ) -> AuditEvent:
        return AuditEvent(
            tenant_id=competitor.tenant_id,
            event_type=event_type,
            resource_type="workspace_competitor",
            resource_id=competitor.id,
            actor_id=actor_id,
            details={
                "workspace_id": str(competitor.workspace_id),
                "changed_fields": changed_fields,
            },
        )

    async def _persist_competitor(self, competitor: WorkspaceCompetitor) -> WorkspaceCompetitor:
        try:
            await self.repository.flush()
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        except Exception:
            await self.repository.rollback()
            raise
        await self.repository.refresh(competitor)
        return competitor

    @staticmethod
    def _autonomy_policy_audit(
        policy: WorkspaceAutonomyPolicy,
        event_type: str,
        changed_fields: list[str],
        actor_id: UUID | None,
    ) -> AuditEvent:
        return AuditEvent(
            tenant_id=policy.tenant_id,
            event_type=event_type,
            resource_type="workspace_autonomy_policy",
            resource_id=policy.id,
            actor_id=actor_id,
            details={
                "workspace_id": str(policy.workspace_id),
                "changed_fields": changed_fields,
            },
        )

    async def _persist_autonomy_policy(
        self, policy: WorkspaceAutonomyPolicy
    ) -> WorkspaceAutonomyPolicy:
        try:
            await self.repository.flush()
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        except Exception:
            await self.repository.rollback()
            raise
        await self.repository.refresh(policy)
        return policy

    @staticmethod
    def _goal_audit(
        goal: WorkspacePrimaryGrowthGoal,
        event_type: str,
        changed_fields: list[str],
        actor_id: UUID | None,
    ) -> AuditEvent:
        return AuditEvent(
            tenant_id=goal.tenant_id,
            event_type=event_type,
            resource_type="workspace_primary_growth_goal",
            resource_id=goal.id,
            actor_id=actor_id,
            details={"workspace_id": str(goal.workspace_id), "changed_fields": changed_fields},
        )

    async def _persist_goal(self, goal: WorkspacePrimaryGrowthGoal) -> WorkspacePrimaryGrowthGoal:
        try:
            await self.repository.flush()
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        except Exception:
            await self.repository.rollback()
            raise
        await self.repository.refresh(goal)
        return goal

    @staticmethod
    def _profile_audit(
        profile: WorkspaceBusinessProfile,
        event_type: str,
        changed_fields: list[str],
        actor_id: UUID | None,
    ) -> AuditEvent:
        return AuditEvent(
            tenant_id=profile.tenant_id,
            event_type=event_type,
            resource_type="workspace_business_profile",
            resource_id=profile.id,
            actor_id=actor_id,
            details={
                "workspace_id": str(profile.workspace_id),
                "changed_fields": changed_fields,
            },
        )

    async def _persist_profile(self, profile: WorkspaceBusinessProfile) -> WorkspaceBusinessProfile:
        try:
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        except Exception:
            await self.repository.rollback()
            raise
        await self.repository.refresh(profile)
        return profile

    async def _persist(self, entity: Entity) -> Entity:
        self.repository.add(entity)
        try:
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        await self.repository.refresh(entity)
        return entity
