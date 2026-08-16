from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from growth_os.db.base import Base
from growth_os.db.models import ActionProposal, AuditEvent, ExecutionJob, ExecutionRun
from growth_os.execution import ExecutionStatus
from growth_os.repositories import TenantContext

ExecutionOwned = TypeVar("ExecutionOwned", ExecutionJob, ActionProposal)


class ExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_all(self, *entities: Base) -> None:
        self.session.add_all(entities)

    async def get_owned(
        self, model: type[ExecutionOwned], context: TenantContext, resource_id: UUID
    ) -> ExecutionOwned | None:
        return cast(
            ExecutionOwned | None,
            await self.session.scalar(
                select(model).where(model.id == resource_id, model.tenant_id == context.tenant_id)
            ),
        )

    async def get_job_by_idempotency_key(
        self, context: TenantContext, idempotency_key: str
    ) -> ExecutionJob | None:
        return cast(
            ExecutionJob | None,
            await self.session.scalar(
                select(ExecutionJob).where(
                    ExecutionJob.tenant_id == context.tenant_id,
                    ExecutionJob.idempotency_key == idempotency_key,
                )
            ),
        )

    async def latest_run(self, context: TenantContext, job_id: UUID) -> ExecutionRun | None:
        return cast(
            ExecutionRun | None,
            await self.session.scalar(
                select(ExecutionRun)
                .where(
                    ExecutionRun.tenant_id == context.tenant_id,
                    ExecutionRun.job_id == job_id,
                )
                .order_by(ExecutionRun.attempt_number.desc())
                .limit(1)
            ),
        )

    async def compare_and_set_job_status(
        self,
        context: TenantContext,
        job_id: UUID,
        expected_status: ExecutionStatus,
        target_status: ExecutionStatus,
    ) -> bool:
        updated_id = await self.session.scalar(
            update(ExecutionJob)
            .where(
                ExecutionJob.id == job_id,
                ExecutionJob.tenant_id == context.tenant_id,
                ExecutionJob.status == expected_status,
            )
            .values(status=target_status)
            .returning(ExecutionJob.id)
        )
        return updated_id is not None

    async def compare_and_set_run_status(
        self,
        context: TenantContext,
        run_id: UUID,
        expected_status: ExecutionStatus,
        target_status: ExecutionStatus,
    ) -> bool:
        updated_id = await self.session.scalar(
            update(ExecutionRun)
            .where(
                ExecutionRun.id == run_id,
                ExecutionRun.tenant_id == context.tenant_id,
                ExecutionRun.status == expected_status,
            )
            .values(status=target_status)
            .returning(ExecutionRun.id)
        )
        return updated_id is not None

    async def insert_run(self, run: ExecutionRun) -> ExecutionRun:
        return cast(
            ExecutionRun,
            await self.session.scalar(
                insert(ExecutionRun)
                .values(
                    id=run.id,
                    tenant_id=run.tenant_id,
                    job_id=run.job_id,
                    status=run.status,
                    attempt_number=run.attempt_number,
                    max_attempts=run.max_attempts,
                    retry_delay_seconds=run.retry_delay_seconds,
                    last_error_code=run.last_error_code,
                )
                .returning(ExecutionRun)
            ),
        )

    async def list_jobs_with_latest_runs(
        self,
        context: TenantContext,
        *,
        workspace_id: UUID | None = None,
        status: ExecutionStatus | None = None,
        kind: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[ExecutionJob, ExecutionRun | None]], int]:
        predicate = [ExecutionJob.tenant_id == context.tenant_id]
        if workspace_id is not None:
            predicate.append(ExecutionJob.workspace_id == workspace_id)
        if status is not None:
            predicate.append(ExecutionJob.status == status)
        if kind is not None:
            predicate.append(ExecutionJob.kind == kind)
        jobs = list(
            (
                await self.session.scalars(
                    select(ExecutionJob)
                    .where(*predicate)
                    .order_by(ExecutionJob.created_at, ExecutionJob.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(ExecutionJob).where(*predicate)
        )
        if not jobs:
            return [], total or 0

        runs = await self.session.scalars(
            select(ExecutionRun)
            .where(
                ExecutionRun.tenant_id == context.tenant_id,
                ExecutionRun.job_id.in_([job.id for job in jobs]),
            )
            .order_by(ExecutionRun.job_id, ExecutionRun.attempt_number.desc())
        )
        latest_by_job: dict[UUID, ExecutionRun] = {}
        for run in runs:
            latest_by_job.setdefault(run.job_id, run)
        return [(job, latest_by_job.get(job.id)) for job in jobs], total or 0

    async def list_runs(
        self,
        context: TenantContext,
        job_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ExecutionRun], int]:
        predicate = (
            ExecutionRun.tenant_id == context.tenant_id,
            ExecutionRun.job_id == job_id,
        )
        runs = list(
            (
                await self.session.scalars(
                    select(ExecutionRun)
                    .where(*predicate)
                    .order_by(ExecutionRun.attempt_number, ExecutionRun.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(ExecutionRun).where(*predicate)
        )
        return runs, total or 0

    async def list_owned(
        self,
        model: type[ExecutionOwned],
        context: TenantContext,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ExecutionOwned], int]:
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

    async def list_audit_events(
        self,
        context: TenantContext,
        *,
        event_type: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEvent], int]:
        predicate = [AuditEvent.tenant_id == context.tenant_id]
        if event_type is not None:
            predicate.append(AuditEvent.event_type == event_type)
        if resource_type is not None:
            predicate.append(AuditEvent.resource_type == resource_type)
        if resource_id is not None:
            predicate.append(AuditEvent.resource_id == resource_id)
        if actor_id is not None:
            predicate.append(AuditEvent.actor_id == actor_id)
        events = list(
            (
                await self.session.scalars(
                    select(AuditEvent)
                    .where(*predicate)
                    .order_by(AuditEvent.created_at, AuditEvent.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(AuditEvent).where(*predicate)
        )
        return events, total or 0

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def refresh(self, entity: Base) -> None:
        await self.session.refresh(entity)
