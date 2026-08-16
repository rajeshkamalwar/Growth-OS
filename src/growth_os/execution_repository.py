from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from growth_os.db.base import Base
from growth_os.db.models import ActionProposal, AuditEvent, ExecutionJob, ExecutionRun
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
        self, context: TenantContext, *, limit: int, offset: int
    ) -> tuple[list[AuditEvent], int]:
        predicate = AuditEvent.tenant_id == context.tenant_id
        events = list(
            (
                await self.session.scalars(
                    select(AuditEvent)
                    .where(predicate)
                    .order_by(AuditEvent.created_at, AuditEvent.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(AuditEvent).where(predicate)
        )
        return events, total or 0

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def refresh(self, entity: Base) -> None:
        await self.session.refresh(entity)
