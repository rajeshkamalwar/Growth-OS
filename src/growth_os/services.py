from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from growth_os.api.errors import ConflictError, NotFoundError
from growth_os.db.models import Connector, Membership, Site, Tenant, Workspace
from growth_os.repositories import FoundationRepository, TenantContext

Entity = TypeVar("Entity", Tenant, Workspace, Membership, Site, Connector)
OwnedEntity = TypeVar("OwnedEntity", Workspace, Membership, Site, Connector)


class FoundationService:
    def __init__(self, repository: FoundationRepository) -> None:
        self.repository = repository

    async def create_tenant(self, *, name: str) -> Tenant:
        return await self._persist(Tenant(name=name))

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

    async def _persist(self, entity: Entity) -> Entity:
        self.repository.add(entity)
        try:
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            raise ConflictError from error
        await self.repository.refresh(entity)
        return entity
