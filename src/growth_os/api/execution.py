from collections.abc import AsyncIterator
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from growth_os.api.errors import NotFoundError
from growth_os.api.schemas import (
    ActionProposalCreate,
    ActionProposalResponse,
    ApprovalDecisionCreate,
    ApprovalDecisionResponse,
    AuditEventResponse,
    ExecutionJobCreate,
    ExecutionJobResponse,
    ExecutionRunResponse,
    Page,
    Pagination,
)
from growth_os.db.models import ActionProposal
from growth_os.execution_repository import ExecutionRepository
from growth_os.execution_service import ExecutionService, JobResult
from growth_os.repositories import TenantContext

ResponseT = TypeVar("ResponseT")


def create_execution_router(session_factory: async_sessionmaker[AsyncSession]) -> APIRouter:
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

    def service(session: AsyncSession) -> ExecutionService:
        return ExecutionService(ExecutionRepository(session))

    def page(items: list[ResponseT], total: int, limit: int, offset: int) -> Page[ResponseT]:
        return Page(items=items, pagination=Pagination(limit=limit, offset=offset, total=total))

    def job_response(result: JobResult) -> ExecutionJobResponse:
        job = ExecutionJobResponse.model_validate(
            {
                **result.job.__dict__,
                "latest_run": ExecutionRunResponse.model_validate(result.latest_run),
            }
        )
        return job

    @router.post(
        "/tenants/{tenant_id}/execution-jobs",
        response_model=ExecutionJobResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_job(
        payload: ExecutionJobCreate, context: Context, session: Session, response: Response
    ) -> ExecutionJobResponse:
        result = await service(session).create_job(
            context,
            workspace_id=payload.workspace_id,
            kind=payload.kind,
            idempotency_key=payload.idempotency_key,
            max_attempts=payload.max_attempts,
            retry_delay_seconds=payload.retry_delay_seconds,
        )
        if not result.created:
            response.status_code = status.HTTP_200_OK
        return job_response(result)

    @router.get("/tenants/{tenant_id}/execution-jobs", response_model=Page[ExecutionJobResponse])
    async def list_jobs(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[ExecutionJobResponse]:
        results, total = await service(session).list_jobs(context, limit=limit, offset=offset)
        return page([job_response(result) for result in results], total, limit, offset)

    @router.get(
        "/tenants/{tenant_id}/execution-jobs/{resource_id}",
        response_model=ExecutionJobResponse,
    )
    async def get_job(
        resource_id: UUID, context: Context, session: Session
    ) -> ExecutionJobResponse:
        return job_response(await service(session).get_job(context, resource_id))

    @router.post(
        "/tenants/{tenant_id}/action-proposals",
        response_model=ActionProposalResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_proposal(
        payload: ActionProposalCreate, context: Context, session: Session
    ) -> object:
        return await service(session).create_proposal(
            context,
            job_id=payload.job_id,
            action_type=payload.action_type,
            description=payload.description,
            risk_level=payload.risk_level,
            requires_approval=payload.requires_approval,
        )

    @router.get(
        "/tenants/{tenant_id}/action-proposals", response_model=Page[ActionProposalResponse]
    )
    async def list_proposals(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[ActionProposalResponse]:
        proposals, total = await service(session).repository.list_owned(
            ActionProposal, context, limit=limit, offset=offset
        )
        return page(
            [ActionProposalResponse.model_validate(item) for item in proposals],
            total,
            limit,
            offset,
        )

    @router.get(
        "/tenants/{tenant_id}/action-proposals/{resource_id}",
        response_model=ActionProposalResponse,
    )
    async def get_proposal(resource_id: UUID, context: Context, session: Session) -> object:
        return await service(session).get_owned(ActionProposal, context, resource_id)

    @router.post(
        "/tenants/{tenant_id}/action-proposals/{resource_id}/decisions",
        response_model=ApprovalDecisionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def decide_proposal(
        resource_id: UUID,
        payload: ApprovalDecisionCreate,
        context: Context,
        session: Session,
    ) -> object:
        return await service(session).decide_proposal(
            context,
            resource_id,
            decision=payload.decision,
            decided_by=payload.decided_by,
            reason=payload.reason,
        )

    @router.get("/tenants/{tenant_id}/audit-events", response_model=Page[AuditEventResponse])
    async def list_audit_events(
        context: Context, session: Session, limit: Limit = 50, offset: Offset = 0
    ) -> Page[AuditEventResponse]:
        events, total = await service(session).repository.list_audit_events(
            context, limit=limit, offset=offset
        )
        return page(
            [AuditEventResponse.model_validate(item) for item in events], total, limit, offset
        )

    return router
