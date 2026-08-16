import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from growth_os.db.base import Base
from growth_os.db.models import (
    ActionProposal,
    ExecutionJob,
    ExecutionRun,
    ProposalStatus,
    RiskLevel,
    Tenant,
    Workspace,
)
from growth_os.execution import ExecutionStatus
from growth_os.execution_repository import ExecutionRepository
from growth_os.repositories import TenantContext


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as database_session:
        yield database_session

    await engine.dispose()


async def test_database_rejects_high_risk_proposal_without_approval(
    session: AsyncSession,
) -> None:
    tenant = Tenant(name="Tenant")
    workspace = Workspace(tenant_id=tenant.id, name="Workspace")
    session.add_all([tenant, workspace])
    await session.commit()
    job = ExecutionJob(
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        kind="site_analysis",
        idempotency_key="job-1",
        status=ExecutionStatus.QUEUED,
    )
    session.add(job)
    await session.commit()

    proposal = ActionProposal(
        tenant_id=tenant.id,
        job_id=job.id,
        action_type="publish_content",
        description="Unsafe direct insert",
        risk_level=RiskLevel.HIGH,
        requires_approval=False,
        status=ProposalStatus.APPROVED,
    )
    session.add(proposal)

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_job_page_loads_latest_runs_with_bounded_queries(session: AsyncSession) -> None:
    tenant = Tenant(name="Tenant")
    workspace = Workspace(tenant_id=tenant.id, name="Workspace")
    session.add_all([tenant, workspace])
    await session.commit()
    jobs = [
        ExecutionJob(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            kind="site_analysis",
            idempotency_key=f"job-{index}",
            status=ExecutionStatus.QUEUED,
        )
        for index in range(3)
    ]
    session.add_all(jobs)
    await session.commit()
    session.add_all(
        ExecutionRun(
            tenant_id=tenant.id,
            job_id=job.id,
            status=ExecutionStatus.QUEUED,
            attempt_number=1,
            max_attempts=3,
            retry_delay_seconds=0,
        )
        for job in jobs
    )
    await session.commit()

    query_count = 0
    engine = session.bind
    assert engine is not None

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_queries(*_args) -> None:
        nonlocal query_count
        query_count += 1

    page, total = await ExecutionRepository(session).list_jobs_with_latest_runs(
        TenantContext(tenant_id=tenant.id), limit=100, offset=0
    )

    assert total == 3
    assert len(page) == 3
    assert all(run is not None and run.attempt_number == 1 for _job, run in page)
    assert query_count == 3
