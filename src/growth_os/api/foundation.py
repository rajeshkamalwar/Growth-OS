from collections.abc import AsyncIterator
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from growth_os.api.errors import NotFoundError
from growth_os.api.schemas import (
    ConnectorStatusCreate,
    ConnectorStatusResponse,
    ConnectorStatusUpdate,
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
    Page,
    Pagination,
    SiteCreate,
    SiteResponse,
    SiteUpdate,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from growth_os.db.models import Connector, Membership, Site, Workspace
from growth_os.repositories import FoundationRepository, TenantContext
from growth_os.services import FoundationService

ResponseT = TypeVar("ResponseT")


def create_foundation_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    Session = Annotated[AsyncSession, Depends(get_session)]

    def tenant_context(
        tenant_id: UUID,
        x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
    ) -> TenantContext:
        if x_tenant_id != tenant_id:
            raise NotFoundError
        return TenantContext(tenant_id=tenant_id)

    Context = Annotated[TenantContext, Depends(tenant_context)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0)]

    def service(session: AsyncSession) -> FoundationService:
        return FoundationService(FoundationRepository(session))

    def page(items: list[ResponseT], total: int, limit: int, offset: int) -> Page[ResponseT]:
        return Page(
            items=items,
            pagination=Pagination(limit=limit, offset=offset, total=total),
        )

    @router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
    async def create_tenant(payload: TenantCreate, session: Session) -> object:
        return await service(session).create_tenant(name=payload.name)

    @router.get("/tenants/{tenant_id}", response_model=TenantResponse)
    async def get_tenant(context: Context, session: Session) -> object:
        return await service(session).get_tenant(context)

    @router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
    async def update_tenant(payload: TenantUpdate, context: Context, session: Session) -> object:
        return await service(session).update_tenant(context, name=payload.name)

    @router.post(
        "/tenants/{tenant_id}/workspaces",
        response_model=WorkspaceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_workspace(
        payload: WorkspaceCreate, context: Context, session: Session
    ) -> object:
        return await service(session).create_workspace(context, name=payload.name)

    @router.get("/tenants/{tenant_id}/workspaces", response_model=Page[WorkspaceResponse])
    async def list_workspaces(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[WorkspaceResponse]:
        items, total = await service(session).list_owned(
            Workspace, context, limit=limit, offset=offset
        )
        return page(
            [WorkspaceResponse.model_validate(item) for item in items], total, limit, offset
        )

    @router.get("/tenants/{tenant_id}/workspaces/{resource_id}", response_model=WorkspaceResponse)
    async def get_workspace(resource_id: UUID, context: Context, session: Session) -> object:
        return await service(session).get_owned(Workspace, context, resource_id)

    @router.patch("/tenants/{tenant_id}/workspaces/{resource_id}", response_model=WorkspaceResponse)
    async def update_workspace(
        resource_id: UUID,
        payload: WorkspaceUpdate,
        context: Context,
        session: Session,
    ) -> object:
        return await service(session).update_owned(
            Workspace, context, resource_id, {"name": payload.name}
        )

    @router.post(
        "/tenants/{tenant_id}/memberships",
        response_model=MembershipResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_membership(
        payload: MembershipCreate, context: Context, session: Session
    ) -> object:
        return await service(session).create_membership(
            context,
            workspace_id=payload.workspace_id,
            user_id=payload.user_id,
            role=payload.role,
        )

    @router.get("/tenants/{tenant_id}/memberships", response_model=Page[MembershipResponse])
    async def list_memberships(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[MembershipResponse]:
        items, total = await service(session).list_owned(
            Membership, context, limit=limit, offset=offset
        )
        return page(
            [MembershipResponse.model_validate(item) for item in items], total, limit, offset
        )

    @router.get("/tenants/{tenant_id}/memberships/{resource_id}", response_model=MembershipResponse)
    async def get_membership(resource_id: UUID, context: Context, session: Session) -> object:
        return await service(session).get_owned(Membership, context, resource_id)

    @router.patch(
        "/tenants/{tenant_id}/memberships/{resource_id}", response_model=MembershipResponse
    )
    async def update_membership(
        resource_id: UUID,
        payload: MembershipUpdate,
        context: Context,
        session: Session,
    ) -> object:
        return await service(session).update_owned(
            Membership, context, resource_id, {"role": payload.role}
        )

    @router.post(
        "/tenants/{tenant_id}/sites",
        response_model=SiteResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_site(payload: SiteCreate, context: Context, session: Session) -> object:
        return await service(session).create_site(
            context,
            workspace_id=payload.workspace_id,
            name=payload.name,
            url=str(payload.url),
        )

    @router.get("/tenants/{tenant_id}/sites", response_model=Page[SiteResponse])
    async def list_sites(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[SiteResponse]:
        items, total = await service(session).list_owned(Site, context, limit=limit, offset=offset)
        return page([SiteResponse.model_validate(item) for item in items], total, limit, offset)

    @router.get("/tenants/{tenant_id}/sites/{resource_id}", response_model=SiteResponse)
    async def get_site(resource_id: UUID, context: Context, session: Session) -> object:
        return await service(session).get_owned(Site, context, resource_id)

    @router.patch("/tenants/{tenant_id}/sites/{resource_id}", response_model=SiteResponse)
    async def update_site(
        resource_id: UUID, payload: SiteUpdate, context: Context, session: Session
    ) -> object:
        changes = payload.model_dump(exclude_unset=True)
        if "url" in changes:
            changes["url"] = str(changes["url"])
        return await service(session).update_owned(Site, context, resource_id, changes)

    @router.post(
        "/tenants/{tenant_id}/connector-statuses",
        response_model=ConnectorStatusResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_connector_status(
        payload: ConnectorStatusCreate, context: Context, session: Session
    ) -> object:
        return await service(session).create_connector(
            context,
            workspace_id=payload.workspace_id,
            site_id=payload.site_id,
            kind=payload.kind,
        )

    @router.get(
        "/tenants/{tenant_id}/connector-statuses",
        response_model=Page[ConnectorStatusResponse],
    )
    async def list_connector_statuses(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[ConnectorStatusResponse]:
        items, total = await service(session).list_owned(
            Connector, context, limit=limit, offset=offset
        )
        return page(
            [ConnectorStatusResponse.model_validate(item) for item in items],
            total,
            limit,
            offset,
        )

    @router.get(
        "/tenants/{tenant_id}/connector-statuses/{resource_id}",
        response_model=ConnectorStatusResponse,
    )
    async def get_connector_status(resource_id: UUID, context: Context, session: Session) -> object:
        return await service(session).get_owned(Connector, context, resource_id)

    @router.patch(
        "/tenants/{tenant_id}/connector-statuses/{resource_id}",
        response_model=ConnectorStatusResponse,
    )
    async def update_connector_status(
        resource_id: UUID,
        payload: ConnectorStatusUpdate,
        context: Context,
        session: Session,
    ) -> object:
        return await service(session).update_owned(
            Connector, context, resource_id, {"status": payload.status}
        )

    return router
