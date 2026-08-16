import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.db.models import AuditEvent, ExecutionJob, ExecutionRun
from growth_os.execution import ALLOWED_TRANSITIONS, ExecutionStatus
from growth_os.execution_repository import ExecutionRepository
from growth_os.main import create_app
from growth_os.repositories import TenantContext


@pytest.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'execution.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(readiness_probe=_ready, session_factory=session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api_client:
        yield api_client


async def _ready() -> None:
    return None


async def setup_tenant(
    client: AsyncClient, name: str
) -> tuple[dict[str, object], dict[str, object]]:
    tenant_response = await client.post("/api/v1/tenants", json={"name": name})
    tenant = tenant_response.json()
    workspace_response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/workspaces",
        headers={"X-Tenant-ID": str(tenant["id"])},
        json={"name": "Primary"},
    )
    return tenant, workspace_response.json()


def headers(tenant: dict[str, object]) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant["id"])}


async def create_job(
    client: AsyncClient,
    tenant: dict[str, object],
    workspace: dict[str, object],
    *,
    key: str = "crawl-homepage-1",
    kind: str = "site_analysis",
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs",
        headers=headers(tenant),
        json={
            "workspace_id": workspace["id"],
            "kind": kind,
            "idempotency_key": key,
            "max_attempts": 3,
        },
    )
    assert response.status_code == 201
    return response.json()


async def transition_job(
    client: AsyncClient,
    tenant: dict[str, object],
    job: dict[str, object],
    expected_status: ExecutionStatus,
    target_status: ExecutionStatus,
    *,
    actor_id: str | None = None,
) -> Response:
    payload = {
        "expected_status": expected_status.value,
        "target_status": target_status.value,
    }
    if actor_id is not None:
        payload["actor_id"] = actor_id
    return await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}/transitions",
        headers=headers(tenant),
        json=payload,
    )


async def retry_job(
    client: AsyncClient,
    tenant: dict[str, object],
    job: dict[str, object],
    expected_attempt_number: int,
    *,
    actor_id: str | None = None,
) -> Response:
    payload: dict[str, object] = {"expected_attempt_number": expected_attempt_number}
    if actor_id is not None:
        payload["actor_id"] = actor_id
    return await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}/retries",
        headers=headers(tenant),
        json=payload,
    )


async def list_runs(
    client: AsyncClient,
    tenant: dict[str, object],
    job: dict[str, object],
    *,
    limit: int = 50,
    offset: int = 0,
) -> Response:
    return await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}/runs"
        f"?limit={limit}&offset={offset}",
        headers=headers(tenant),
    )


async def set_job_and_run_status(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: object,
    job_id: object,
    status: ExecutionStatus,
) -> None:
    tenant_uuid = UUID(str(tenant_id))
    job_uuid = UUID(str(job_id))
    async with session_factory() as session:
        await session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.tenant_id == tenant_uuid, ExecutionJob.id == job_uuid)
            .values(status=status)
        )
        await session.execute(
            update(ExecutionRun)
            .where(ExecutionRun.tenant_id == tenant_uuid, ExecutionRun.job_id == job_uuid)
            .values(status=status)
        )
        await session.commit()


async def create_proposal(
    client: AsyncClient,
    tenant: dict[str, object],
    job: dict[str, object],
    *,
    risk_level: str = "high",
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/action-proposals",
        headers=headers(tenant),
        json={
            "job_id": job["id"],
            "action_type": "website_change",
            "description": "Change the home page title",
            "risk_level": risk_level,
            "requires_approval": True,
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_job_creation_is_idempotent_and_exposes_retry_metadata(client: AsyncClient) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant A")
    first = await create_job(client, tenant, workspace)

    duplicate_response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs",
        headers=headers(tenant),
        json={
            "workspace_id": workspace["id"],
            "kind": "site_analysis",
            "idempotency_key": "crawl-homepage-1",
            "max_attempts": 3,
        },
    )

    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["id"] == first["id"]
    assert first["status"] == "queued"
    assert first["latest_run"]["attempt_number"] == 1
    assert first["latest_run"]["max_attempts"] == 3
    assert first["latest_run"]["status"] == "queued"


async def test_idempotency_key_reuse_with_different_request_conflicts(client: AsyncClient) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant A")
    await create_job(client, tenant, workspace)

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs",
        headers=headers(tenant),
        json={
            "workspace_id": workspace["id"],
            "kind": "different_analysis",
            "idempotency_key": "crawl-homepage-1",
            "max_attempts": 3,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_identical_request_recovers_when_idempotency_insert_loses_race(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant A")
    first = await create_job(client, tenant, workspace)
    original_lookup = ExecutionRepository.get_job_by_idempotency_key
    stale_read = True

    async def miss_once_then_read_winner(
        repository: ExecutionRepository,
        context: TenantContext,
        idempotency_key: str,
    ) -> ExecutionJob | None:
        nonlocal stale_read
        if stale_read:
            stale_read = False
            return None
        return await original_lookup(repository, context, idempotency_key)

    monkeypatch.setattr(
        ExecutionRepository,
        "get_job_by_idempotency_key",
        miss_once_then_read_winner,
    )

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs",
        headers=headers(tenant),
        json={
            "workspace_id": workspace["id"],
            "kind": "site_analysis",
            "idempotency_key": "crawl-homepage-1",
            "max_attempts": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == first["id"]


async def test_same_idempotency_key_is_isolated_by_tenant(client: AsyncClient) -> None:
    tenant_a, workspace_a = await setup_tenant(client, "Tenant A")
    tenant_b, workspace_b = await setup_tenant(client, "Tenant B")

    job_a = await create_job(client, tenant_a, workspace_a, key="shared-key")
    job_b = await create_job(client, tenant_b, workspace_b, key="shared-key")

    assert job_a["id"] != job_b["id"]


async def test_cross_tenant_job_and_proposal_access_fails_safely(client: AsyncClient) -> None:
    tenant_a, _workspace_a = await setup_tenant(client, "Tenant A")
    tenant_b, workspace_b = await setup_tenant(client, "Tenant B")
    job_b = await create_job(client, tenant_b, workspace_b)
    proposal_b = await create_proposal(client, tenant_b, job_b)

    job_response = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs/{job_b['id']}",
        headers=headers(tenant_a),
    )
    decision_response = await client.post(
        f"/api/v1/tenants/{tenant_a['id']}/action-proposals/{proposal_b['id']}/decisions",
        headers=headers(tenant_a),
        json={"decision": "approved", "decided_by": str(uuid4())},
    )

    assert job_response.status_code == 404
    assert decision_response.status_code == 404
    assert decision_response.json()["error"]["code"] == "not_found"


async def test_job_and_proposal_lists_are_tenant_scoped(client: AsyncClient) -> None:
    tenant_a, workspace_a = await setup_tenant(client, "Tenant A")
    tenant_b, workspace_b = await setup_tenant(client, "Tenant B")
    job_a = await create_job(client, tenant_a, workspace_a, key="tenant-a-job")
    await create_job(client, tenant_b, workspace_b, key="tenant-b-job")
    proposal_a = await create_proposal(client, tenant_a, job_a)

    jobs_response = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs",
        headers=headers(tenant_a),
    )
    proposals_response = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/action-proposals",
        headers=headers(tenant_a),
    )

    assert jobs_response.status_code == 200
    assert [item["id"] for item in jobs_response.json()["items"]] == [job_a["id"]]
    assert proposals_response.status_code == 200
    assert [item["id"] for item in proposals_response.json()["items"]] == [proposal_a["id"]]


async def test_job_list_filters_individually_and_composes_with_and_semantics(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace_a = await setup_tenant(client, "Filtered Jobs")
    workspace_response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/workspaces",
        headers=headers(tenant),
        json={"name": "Secondary"},
    )
    workspace_b = workspace_response.json()
    queued_site = await create_job(client, tenant, workspace_a, key="queued-site")
    running_site = await create_job(client, tenant, workspace_a, key="running-site")
    queued_report = await create_job(
        client, tenant, workspace_b, key="queued-report", kind="daily_report"
    )
    await set_job_and_run_status(
        session_factory, tenant["id"], running_site["id"], ExecutionStatus.RUNNING
    )

    async def filtered(query: str) -> dict[str, object]:
        response = await client.get(
            f"/api/v1/tenants/{tenant['id']}/execution-jobs?{query}",
            headers=headers(tenant),
        )
        assert response.status_code == 200
        return response.json()

    by_workspace = await filtered(f"workspace_id={workspace_a['id']}")
    by_status = await filtered("status=running")
    by_kind = await filtered("kind=daily_report")
    composed = await filtered(f"workspace_id={workspace_a['id']}&status=queued&kind=site_analysis")

    assert {item["id"] for item in by_workspace["items"]} == {
        queued_site["id"],
        running_site["id"],
    }
    assert [item["id"] for item in by_status["items"]] == [running_site["id"]]
    assert [item["id"] for item in by_kind["items"]] == [queued_report["id"]]
    assert [item["id"] for item in composed["items"]] == [queued_site["id"]]
    assert composed["pagination"]["total"] == 1


async def test_filtered_job_list_paginates_with_full_total_and_valid_empty_page(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Filtered Pagination")
    first = await create_job(client, tenant, workspace, key="first-report", kind="report")
    second = await create_job(client, tenant, workspace, key="second-report", kind="report")
    await create_job(client, tenant, workspace, key="analysis", kind="analysis")

    tied_created_at = datetime(2026, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        await session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id.in_([UUID(str(first["id"])), UUID(str(second["id"]))]))
            .values(created_at=tied_created_at)
        )
        await session.commit()

    first_page = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs?kind=report&limit=1&offset=0",
        headers=headers(tenant),
    )
    second_page = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs?kind=report&limit=1&offset=1",
        headers=headers(tenant),
    )
    empty_page = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs?kind=report&limit=1&offset=2",
        headers=headers(tenant),
    )

    ordered_ids = sorted([str(first["id"]), str(second["id"])])
    assert [item["id"] for item in first_page.json()["items"]] == ordered_ids[:1]
    assert [item["id"] for item in second_page.json()["items"]] == ordered_ids[1:]
    assert first_page.json()["pagination"]["total"] == 2
    assert empty_page.json() == {
        "items": [],
        "pagination": {"limit": 1, "offset": 2, "total": 2},
    }


async def test_job_workspace_filter_hides_missing_and_cross_tenant_workspaces(
    client: AsyncClient,
) -> None:
    tenant_a, _workspace_a = await setup_tenant(client, "Filter Tenant A")
    tenant_b, workspace_b = await setup_tenant(client, "Filter Tenant B")
    await create_job(client, tenant_b, workspace_b, key="tenant-b-job")

    missing = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs?workspace_id={uuid4()}",
        headers=headers(tenant_a),
    )
    cross_tenant = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs?workspace_id={workspace_b['id']}",
        headers=headers(tenant_a),
    )

    assert missing.status_code == cross_tenant.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert cross_tenant.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "query",
    [
        "status=unknown",
        "kind=",
        "kind=UPPER",
        f"kind={'a' * 101}",
        "limit=0",
        "limit=101",
        "offset=-1",
    ],
)
async def test_job_filters_retain_structured_validation_errors(
    client: AsyncClient, query: str
) -> None:
    tenant, _workspace = await setup_tenant(client, f"Invalid job filter {query}")

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs?{query}", headers=headers(tenant)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_filtered_job_endpoint_has_no_write_or_audit_side_effect(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Read Only Job Filter")
    await create_job(client, tenant, workspace, key="read-only-job")
    async with session_factory() as session:
        before = (
            await session.scalar(select(func.count()).select_from(ExecutionJob)),
            await session.scalar(select(func.count()).select_from(AuditEvent)),
        )

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs?status=queued",
        headers=headers(tenant),
    )

    async with session_factory() as session:
        after = (
            await session.scalar(select(func.count()).select_from(ExecutionJob)),
            await session.scalar(select(func.count()).select_from(AuditEvent)),
        )
    assert response.status_code == 200
    assert after == before


async def test_filtered_job_repository_is_tenant_safe_deterministic_and_read_only(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a, workspace_a = await setup_tenant(client, "Repository Filter A")
    tenant_b, workspace_b = await setup_tenant(client, "Repository Filter B")
    first = await create_job(client, tenant_a, workspace_a, key="repo-first", kind="report")
    second = await create_job(client, tenant_a, workspace_a, key="repo-second", kind="report")
    await create_job(client, tenant_a, workspace_a, key="repo-other", kind="analysis")
    await create_job(client, tenant_b, workspace_b, key="repo-foreign", kind="report")
    tenant_id = UUID(str(tenant_a["id"]))

    first_id = UUID(str(first["id"]))
    second_id = UUID(str(second["id"]))
    ids_by_uuid = sorted([first_id, second_id], key=str)
    lower_uuid_later_id, higher_uuid_earlier_id = ids_by_uuid
    earlier_created_at = datetime(2026, 1, 1, tzinfo=UTC)

    async with session_factory() as session:
        await session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == higher_uuid_earlier_id)
            .values(created_at=earlier_created_at)
        )
        await session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == lower_uuid_later_id)
            .values(created_at=earlier_created_at + timedelta(seconds=1))
        )
        await session.commit()
        repository = ExecutionRepository(session)
        before = (
            await session.scalar(select(func.count()).select_from(ExecutionJob)),
            await session.scalar(select(func.count()).select_from(AuditEvent)),
        )
        jobs, total = await repository.list_jobs_with_latest_runs(
            TenantContext(tenant_id=tenant_id),
            kind="report",
            limit=1,
            offset=1,
        )
        after = (
            await session.scalar(select(func.count()).select_from(ExecutionJob)),
            await session.scalar(select(func.count()).select_from(AuditEvent)),
        )

    assert total == 2
    assert [job.id for job, _run in jobs] == [lower_uuid_later_id]
    assert after == before


async def test_run_history_returns_all_attempts_in_stable_order_and_existing_shape(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Run History")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    assert (await retry_job(client, tenant, job, 1)).status_code == 200
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    assert (await retry_job(client, tenant, job, 2)).status_code == 200

    response = await list_runs(client, tenant, job)

    assert response.status_code == 200
    body = response.json()
    assert [run["attempt_number"] for run in body["items"]] == [1, 2, 3]
    assert body["pagination"] == {"limit": 50, "offset": 0, "total": 3}
    assert set(body["items"][0]) == {
        "id",
        "tenant_id",
        "job_id",
        "status",
        "attempt_number",
        "max_attempts",
        "retry_delay_seconds",
        "last_error_code",
        "created_at",
        "updated_at",
    }


async def test_run_history_paginates_with_job_specific_total_and_valid_empty_page(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Run Pagination")
    job = await create_job(client, tenant, workspace, key="paged-job")
    other_job = await create_job(client, tenant, workspace, key="other-job")
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    assert (await retry_job(client, tenant, job, 1)).status_code == 200

    first_page = await list_runs(client, tenant, job, limit=1, offset=0)
    second_page = await list_runs(client, tenant, job, limit=1, offset=1)
    empty_page = await list_runs(client, tenant, job, limit=1, offset=2)
    one_attempt = await list_runs(client, tenant, other_job)

    assert first_page.json()["pagination"]["total"] == 2
    assert [run["attempt_number"] for run in first_page.json()["items"]] == [1]
    assert [run["attempt_number"] for run in second_page.json()["items"]] == [2]
    assert empty_page.json() == {
        "items": [],
        "pagination": {"limit": 1, "offset": 2, "total": 2},
    }
    assert len(one_attempt.json()["items"]) == 1
    assert one_attempt.json()["pagination"]["total"] == 1


async def test_run_history_hides_missing_and_cross_tenant_parents_and_isolates_runs(
    client: AsyncClient,
) -> None:
    tenant_a, workspace_a = await setup_tenant(client, "Run Tenant A")
    tenant_b, workspace_b = await setup_tenant(client, "Run Tenant B")
    job_a = await create_job(client, tenant_a, workspace_a, key="run-a")
    other_job_a = await create_job(client, tenant_a, workspace_a, key="other-run-a")
    job_b = await create_job(client, tenant_b, workspace_b, key="run-b")

    visible = await list_runs(client, tenant_a, job_a)
    missing = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs/{uuid4()}/runs",
        headers=headers(tenant_a),
    )
    cross_tenant = await list_runs(client, tenant_a, job_b)

    assert [run["job_id"] for run in visible.json()["items"]] == [job_a["id"]]
    assert visible.json()["pagination"]["total"] == 1
    assert other_job_a["latest_run"]["id"] not in {run["id"] for run in visible.json()["items"]}
    assert missing.status_code == cross_tenant.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert cross_tenant.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
async def test_run_history_reuses_structured_pagination_validation(
    client: AsyncClient, query: str
) -> None:
    tenant, workspace = await setup_tenant(client, f"Invalid run page {query}")
    job = await create_job(client, tenant, workspace)

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}/runs?{query}",
        headers=headers(tenant),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_run_history_repository_is_deterministic_bounded_and_read_only(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Repository Run History")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    assert (await retry_job(client, tenant, job, 1)).status_code == 200
    tenant_id = UUID(str(tenant["id"]))
    job_id = UUID(str(job["id"]))

    async with session_factory() as session:
        repository = ExecutionRepository(session)
        before = (
            await session.scalar(select(func.count()).select_from(ExecutionRun)),
            await session.scalar(select(func.count()).select_from(AuditEvent)),
        )
        runs, total = await repository.list_runs(
            TenantContext(tenant_id=tenant_id), job_id, limit=1, offset=1
        )
        after = (
            await session.scalar(select(func.count()).select_from(ExecutionRun)),
            await session.scalar(select(func.count()).select_from(AuditEvent)),
        )

    assert total == 2
    assert [(run.job_id, run.attempt_number) for run in runs] == [(job_id, 2)]
    assert after == before


async def test_run_history_endpoint_has_no_write_or_audit_side_effect(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Read Only Run History")
    job = await create_job(client, tenant, workspace)
    job_id = UUID(str(job["id"]))
    async with session_factory() as session:
        before_runs = list(
            (
                await session.execute(
                    select(*ExecutionRun.__table__.columns)
                    .where(ExecutionRun.job_id == job_id)
                    .order_by(ExecutionRun.attempt_number, ExecutionRun.id)
                )
            ).all()
        )
        before_audits = await session.scalar(select(func.count()).select_from(AuditEvent))

    response = await list_runs(client, tenant, job)

    async with session_factory() as session:
        after_runs = list(
            (
                await session.execute(
                    select(*ExecutionRun.__table__.columns)
                    .where(ExecutionRun.job_id == job_id)
                    .order_by(ExecutionRun.attempt_number, ExecutionRun.id)
                )
            ).all()
        )
        after_audits = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert response.status_code == 200
    assert after_runs == before_runs
    assert after_audits == before_audits


async def test_approval_is_final_and_records_append_only_decision(client: AsyncClient) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant")
    job = await create_job(client, tenant, workspace)
    proposal = await create_proposal(client, tenant, job)
    decision_payload = {
        "decision": "approved",
        "decided_by": str(uuid4()),
        "reason": "Reviewed and accepted",
    }

    approved = await client.post(
        f"/api/v1/tenants/{tenant['id']}/action-proposals/{proposal['id']}/decisions",
        headers=headers(tenant),
        json=decision_payload,
    )
    repeated = await client.post(
        f"/api/v1/tenants/{tenant['id']}/action-proposals/{proposal['id']}/decisions",
        headers=headers(tenant),
        json={**decision_payload, "decision": "rejected"},
    )

    assert approved.status_code == 201
    assert approved.json()["decision"] == "approved"
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "invalid_state_transition"
    proposal_response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/action-proposals/{proposal['id']}",
        headers=headers(tenant),
    )
    assert proposal_response.json()["status"] == "approved"


async def test_high_risk_proposal_cannot_bypass_approval(client: AsyncClient) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant")
    job = await create_job(client, tenant, workspace)

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/action-proposals",
        headers=headers(tenant),
        json={
            "job_id": job["id"],
            "action_type": "publish_content",
            "description": "Publish content",
            "risk_level": "high",
            "requires_approval": False,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_read_only_proposal_without_approval_is_immediately_approved(
    client: AsyncClient,
) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant")
    job = await create_job(client, tenant, workspace)

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/action-proposals",
        headers=headers(tenant),
        json={
            "job_id": job["id"],
            "action_type": "inspect_site",
            "description": "Read public metadata",
            "risk_level": "read_only",
            "requires_approval": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "approved"


async def test_rejection_and_audit_history_are_paginated(client: AsyncClient) -> None:
    tenant, workspace = await setup_tenant(client, "Tenant")
    job = await create_job(client, tenant, workspace)
    proposal = await create_proposal(client, tenant, job)
    rejected = await client.post(
        f"/api/v1/tenants/{tenant['id']}/action-proposals/{proposal['id']}/decisions",
        headers=headers(tenant),
        json={"decision": "rejected", "decided_by": str(uuid4()), "reason": "Too risky"},
    )
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=2&offset=0",
        headers=headers(tenant),
    )

    assert rejected.status_code == 201
    assert audit.status_code == 200
    body = audit.json()
    assert body["pagination"]["total"] == 3
    assert len(body["items"]) == 2
    assert all(item["tenant_id"] == tenant["id"] for item in body["items"])


async def test_audit_event_filters_work_independently_and_compose_with_and(
    client: AsyncClient,
) -> None:
    tenant, workspace = await setup_tenant(client, "Scoped Audit Filters")
    first_job = await create_job(client, tenant, workspace, key="first-filter-job")
    second_job = await create_job(client, tenant, workspace, key="second-filter-job")
    actor_id = str(uuid4())
    transitioned = await transition_job(
        client,
        tenant,
        first_job,
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        actor_id=actor_id,
    )
    assert transitioned.status_code == 200

    base_url = f"/api/v1/tenants/{tenant['id']}/audit-events"
    by_event = await client.get(
        f"{base_url}?event_type=execution_job.transitioned", headers=headers(tenant)
    )
    by_resource_type = await client.get(
        f"{base_url}?resource_type=execution_job", headers=headers(tenant)
    )
    by_resource_id = await client.get(
        f"{base_url}?resource_id={second_job['id']}", headers=headers(tenant)
    )
    by_actor = await client.get(f"{base_url}?actor_id={actor_id}", headers=headers(tenant))
    composed = await client.get(
        f"{base_url}?event_type=execution_job.transitioned"
        f"&resource_type=execution_job&resource_id={first_job['id']}&actor_id={actor_id}",
        headers=headers(tenant),
    )

    assert [item["resource_id"] for item in by_event.json()["items"]] == [first_job["id"]]
    assert by_event.json()["pagination"]["total"] == 1
    assert by_resource_type.json()["pagination"]["total"] == 3
    assert [item["resource_id"] for item in by_resource_id.json()["items"]] == [second_job["id"]]
    assert by_resource_id.json()["pagination"]["total"] == 1
    assert [item["actor_id"] for item in by_actor.json()["items"]] == [actor_id]
    assert by_actor.json()["pagination"]["total"] == 1
    assert [item["event_type"] for item in composed.json()["items"]] == [
        "execution_job.transitioned"
    ]
    assert composed.json()["pagination"]["total"] == 1


async def test_filtered_audit_events_have_stable_pages_full_totals_and_empty_results(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Paged Audit Filters")
    first_job = await create_job(client, tenant, workspace, key="first-paged-job")
    second_job = await create_job(client, tenant, workspace, key="second-paged-job")
    tied_created_at = datetime(2026, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        await session.execute(
            update(AuditEvent)
            .where(
                AuditEvent.resource_id.in_(
                    [UUID(str(first_job["id"])), UUID(str(second_job["id"]))]
                )
            )
            .values(created_at=tied_created_at)
        )
        await session.commit()

    base_url = (
        f"/api/v1/tenants/{tenant['id']}/audit-events?event_type=execution_job.created&limit=1"
    )
    first_page = await client.get(f"{base_url}&offset=0", headers=headers(tenant))
    second_page = await client.get(f"{base_url}&offset=1", headers=headers(tenant))
    empty_page = await client.get(f"{base_url}&offset=2", headers=headers(tenant))
    unknown = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?event_type=unknown.event",
        headers=headers(tenant),
    )

    ordered_ids = sorted(
        [item["id"] for item in first_page.json()["items"] + second_page.json()["items"]]
    )
    assert [item["id"] for item in first_page.json()["items"]] == ordered_ids[:1]
    assert [item["id"] for item in second_page.json()["items"]] == ordered_ids[1:]
    assert first_page.json()["pagination"]["total"] == 2
    assert empty_page.json() == {
        "items": [],
        "pagination": {"limit": 1, "offset": 2, "total": 2},
    }
    assert unknown.json() == {
        "items": [],
        "pagination": {"limit": 50, "offset": 0, "total": 0},
    }


async def test_audit_filters_preserve_tenant_isolation_when_identifiers_collide(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a, workspace_a = await setup_tenant(client, "Audit Tenant A")
    tenant_b, _workspace_b = await setup_tenant(client, "Audit Tenant B")
    job = await create_job(client, tenant_a, workspace_a, key="colliding-audit-job")
    actor_id = uuid4()
    collision_resource_id = UUID(str(job["id"]))
    async with session_factory() as session:
        session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=UUID(str(tenant_b["id"])),
                event_type="execution_job.created",
                resource_type="execution_job",
                resource_id=collision_resource_id,
                actor_id=actor_id,
                details={},
            )
        )
        await session.commit()

    by_resource = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/audit-events?resource_id={collision_resource_id}",
        headers=headers(tenant_a),
    )
    by_actor = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/audit-events?actor_id={actor_id}",
        headers=headers(tenant_a),
    )

    assert by_resource.json()["pagination"]["total"] == 1
    assert {item["tenant_id"] for item in by_resource.json()["items"]} == {tenant_a["id"]}
    assert by_actor.json()["items"] == []
    assert by_actor.json()["pagination"]["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "event_type=",
        "event_type=Execution.Job",
        "event_type=execution-job.created",
        "event_type=execution..created",
        f"event_type={'a' * 101}",
        "resource_type=",
        "resource_type=ExecutionJob",
        "resource_type=execution-job",
        "resource_type=execution.job",
        f"resource_type={'a' * 101}",
        "resource_id=not-a-uuid",
        "actor_id=not-a-uuid",
        "limit=0",
        "limit=101",
        "offset=-1",
    ],
)
async def test_audit_filters_retain_structured_validation_errors(
    client: AsyncClient, query: str
) -> None:
    tenant, _workspace = await setup_tenant(client, f"Invalid audit filter {query}")

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?{query}", headers=headers(tenant)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_filtered_audit_repository_is_tenant_safe_deterministic_and_read_only(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Audit Repository Filter")
    job = await create_job(client, tenant, workspace, key="repository-audit-job")
    actor_id = str(uuid4())
    assert (
        await transition_job(
            client,
            tenant,
            job,
            ExecutionStatus.QUEUED,
            ExecutionStatus.RUNNING,
            actor_id=actor_id,
        )
    ).status_code == 200

    async with session_factory() as session:
        repository = ExecutionRepository(session)
        before = await session.scalar(select(func.count()).select_from(AuditEvent))
        events, total = await repository.list_audit_events(
            TenantContext(tenant_id=UUID(str(tenant["id"]))),
            event_type="execution_job.transitioned",
            resource_type="execution_job",
            resource_id=UUID(str(job["id"])),
            actor_id=UUID(actor_id),
            limit=1,
            offset=0,
        )
        after = await session.scalar(select(func.count()).select_from(AuditEvent))

    assert total == 1
    assert [event.event_type for event in events] == ["execution_job.transitioned"]
    assert after == before


async def test_filtered_audit_endpoint_has_no_write_or_audit_side_effect(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Read Only Audit Filter")
    job = await create_job(client, tenant, workspace, key="read-only-audit-job")
    async with session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(AuditEvent))

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?resource_id={job['id']}",
        headers=headers(tenant),
    )

    async with session_factory() as session:
        after = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert response.status_code == 200
    assert after == before


@pytest.mark.parametrize(
    ("expected_status", "target_status"),
    [(expected, target) for expected, targets in ALLOWED_TRANSITIONS.items() for target in targets],
)
async def test_every_allowed_execution_edge_transitions_job_and_latest_run(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    expected_status: ExecutionStatus,
    target_status: ExecutionStatus,
) -> None:
    tenant, workspace = await setup_tenant(client, f"{expected_status}-{target_status}")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], expected_status)

    response = await transition_job(client, tenant, job, expected_status, target_status)

    assert response.status_code == 200
    assert response.json()["status"] == target_status.value
    assert response.json()["latest_run"]["status"] == target_status.value


async def test_transition_records_exactly_one_audit_event_with_actor_and_run_details(
    client: AsyncClient,
) -> None:
    tenant, workspace = await setup_tenant(client, "Audited Tenant")
    job = await create_job(client, tenant, workspace)
    actor_id = str(uuid4())

    transitioned = await transition_job(
        client,
        tenant,
        job,
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        actor_id=actor_id,
    )
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=100&offset=0",
        headers=headers(tenant),
    )

    assert transitioned.status_code == 200
    transition_events = [
        event
        for event in audit.json()["items"]
        if event["event_type"] == "execution_job.transitioned"
    ]
    assert len(transition_events) == 1
    event = transition_events[0]
    assert event["resource_id"] == job["id"]
    assert event["actor_id"] == actor_id
    assert event["details"] == {
        "prior_status": "queued",
        "target_status": "running",
        "run_id": job["latest_run"]["id"],
    }


@pytest.mark.parametrize(
    ("expected_status", "target_status"),
    [
        (ExecutionStatus.QUEUED, ExecutionStatus.SUCCEEDED),
        (ExecutionStatus.SUCCEEDED, ExecutionStatus.RUNNING),
    ],
)
async def test_invalid_and_terminal_transitions_fail_without_an_audit_event(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    expected_status: ExecutionStatus,
    target_status: ExecutionStatus,
) -> None:
    tenant, workspace = await setup_tenant(client, "Invalid Transition Tenant")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], expected_status)

    response = await transition_job(client, tenant, job, expected_status, target_status)
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=100&offset=0",
        headers=headers(tenant),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"
    assert all(
        event["event_type"] != "execution_job.transitioned" for event in audit.json()["items"]
    )


async def test_stale_and_repeated_transition_attempts_fail_without_extra_audit(
    client: AsyncClient,
) -> None:
    tenant, workspace = await setup_tenant(client, "Stale Tenant")
    job = await create_job(client, tenant, workspace)

    first = await transition_job(
        client, tenant, job, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING
    )
    repeated = await transition_job(
        client, tenant, job, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING
    )
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=100&offset=0",
        headers=headers(tenant),
    )

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "invalid_state_transition"
    assert (
        sum(event["event_type"] == "execution_job.transitioned" for event in audit.json()["items"])
        == 1
    )


async def test_two_competing_transitions_from_same_state_cannot_both_succeed(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, workspace = await setup_tenant(client, "Competing Tenant")
    job = await create_job(client, tenant, workspace)
    original_compare_and_set = ExecutionRepository.compare_and_set_job_status
    both_callers_ready = asyncio.Event()
    update_lock = asyncio.Lock()
    callers = 0

    async def synchronize_competing_callers(
        repository: ExecutionRepository,
        context: TenantContext,
        job_id: UUID,
        expected_status: ExecutionStatus,
        target_status: ExecutionStatus,
    ) -> bool:
        nonlocal callers
        callers += 1
        if callers == 2:
            both_callers_ready.set()
        await both_callers_ready.wait()
        async with update_lock:
            return await original_compare_and_set(
                repository, context, job_id, expected_status, target_status
            )

    monkeypatch.setattr(
        ExecutionRepository, "compare_and_set_job_status", synchronize_competing_callers
    )
    responses = await asyncio.gather(
        transition_job(client, tenant, job, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING),
        transition_job(client, tenant, job, ExecutionStatus.QUEUED, ExecutionStatus.CANCELLED),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "invalid_state_transition"
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=100&offset=0",
        headers=headers(tenant),
    )
    assert (
        sum(event["event_type"] == "execution_job.transitioned" for event in audit.json()["items"])
        == 1
    )


async def test_inconsistent_job_and_latest_run_fails_closed(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Inconsistent Tenant")
    job = await create_job(client, tenant, workspace)
    async with session_factory() as session:
        await session.execute(
            update(ExecutionRun)
            .where(ExecutionRun.id == UUID(str(job["latest_run"]["id"])))
            .values(status=ExecutionStatus.RUNNING)
        )
        await session.commit()

    response = await transition_job(
        client, tenant, job, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"
    current = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}",
        headers=headers(tenant),
    )
    assert current.json()["status"] == "queued"
    assert current.json()["latest_run"]["status"] == "running"


async def test_missing_and_cross_tenant_transition_requests_fail_safely(
    client: AsyncClient,
) -> None:
    tenant_a, _ = await setup_tenant(client, "Tenant A Transition")
    tenant_b, workspace_b = await setup_tenant(client, "Tenant B Transition")
    job_b = await create_job(client, tenant_b, workspace_b)

    missing = await client.post(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs/{uuid4()}/transitions",
        headers=headers(tenant_a),
        json={"expected_status": "queued", "target_status": "running"},
    )
    cross_tenant = await transition_job(
        client, tenant_a, job_b, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING
    )

    assert missing.status_code == 404
    assert cross_tenant.status_code == 404
    current = await client.get(
        f"/api/v1/tenants/{tenant_b['id']}/execution-jobs/{job_b['id']}",
        headers=headers(tenant_b),
    )
    assert current.json()["status"] == "queued"


async def test_transition_request_is_strict(client: AsyncClient) -> None:
    tenant, workspace = await setup_tenant(client, "Strict Tenant")
    job = await create_job(client, tenant, workspace)

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}/transitions",
        headers=headers(tenant),
        json={
            "expected_status": "queued",
            "target_status": "running",
            "unexpected": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_run_compare_and_set_failure_rolls_back_job_and_audit(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, workspace = await setup_tenant(client, "Rollback Tenant")
    job = await create_job(client, tenant, workspace)

    async def lose_run_compare_and_set(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(ExecutionRepository, "compare_and_set_run_status", lose_run_compare_and_set)
    response = await transition_job(
        client, tenant, job, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING
    )

    assert response.status_code == 409
    current = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}",
        headers=headers(tenant),
    )
    assert current.json()["status"] == "queued"
    assert current.json()["latest_run"]["status"] == "queued"
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=100&offset=0",
        headers=headers(tenant),
    )
    assert all(
        event["event_type"] != "execution_job.transitioned" for event in audit.json()["items"]
    )


async def test_retry_reserves_next_attempt_preserves_history_and_records_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Retry Tenant")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    async with session_factory() as session:
        prior_run = await session.get(ExecutionRun, UUID(str(job["latest_run"]["id"])))
        assert prior_run is not None
        prior_run.max_attempts = 7
        prior_run.retry_delay_seconds = 43
        prior_run.last_error_code = "provider_timeout"
        await session.commit()
        await session.refresh(prior_run)
        prior_before = {
            column.name: getattr(prior_run, column.name)
            for column in ExecutionRun.__table__.columns
        }
    actor_id = str(uuid4())

    response = await retry_job(client, tenant, job, 1, actor_id=actor_id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["latest_run"]["attempt_number"] == 2
    assert body["latest_run"]["status"] == "queued"
    assert body["latest_run"]["max_attempts"] == 7
    assert body["latest_run"]["retry_delay_seconds"] == 43
    assert body["latest_run"]["last_error_code"] is None
    async with session_factory() as session:
        runs = list(
            (
                await session.scalars(
                    select(ExecutionRun)
                    .where(ExecutionRun.job_id == UUID(str(job["id"])))
                    .order_by(ExecutionRun.attempt_number)
                )
            ).all()
        )
        prior_after = {
            column.name: getattr(runs[0], column.name) for column in ExecutionRun.__table__.columns
        }
    assert prior_after == prior_before
    assert [(run.attempt_number, run.status) for run in runs] == [
        (1, ExecutionStatus.FAILED),
        (2, ExecutionStatus.QUEUED),
    ]
    audit = await client.get(
        f"/api/v1/tenants/{tenant['id']}/audit-events?limit=100&offset=0",
        headers=headers(tenant),
    )
    events = [
        event
        for event in audit.json()["items"]
        if event["event_type"] == "execution_job.retry_reserved"
    ]
    assert len(events) == 1
    assert events[0]["actor_id"] == actor_id
    assert events[0]["details"] == {
        "prior_run_id": job["latest_run"]["id"],
        "new_run_id": body["latest_run"]["id"],
        "prior_attempt_number": 1,
        "new_attempt_number": 2,
    }


@pytest.mark.parametrize("status", [ExecutionStatus.QUEUED, ExecutionStatus.RUNNING])
async def test_retry_rejects_non_failed_state_without_side_effects(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    status: ExecutionStatus,
) -> None:
    tenant, workspace = await setup_tenant(client, f"Retry {status}")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], status)

    response = await retry_job(client, tenant, job, 1)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"


@pytest.mark.parametrize(
    ("job_status", "run_status"),
    [
        (ExecutionStatus.FAILED, ExecutionStatus.QUEUED),
        (ExecutionStatus.QUEUED, ExecutionStatus.FAILED),
    ],
)
async def test_retry_rejects_inconsistent_job_and_run_without_side_effects(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    job_status: ExecutionStatus,
    run_status: ExecutionStatus,
) -> None:
    tenant, workspace = await setup_tenant(client, f"Retry mismatch {job_status} {run_status}")
    job = await create_job(client, tenant, workspace)
    tenant_id = UUID(str(tenant["id"]))
    job_id = UUID(str(job["id"]))
    async with session_factory() as session:
        await session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.tenant_id == tenant_id, ExecutionJob.id == job_id)
            .values(status=job_status)
        )
        await session.execute(
            update(ExecutionRun)
            .where(ExecutionRun.tenant_id == tenant_id, ExecutionRun.job_id == job_id)
            .values(status=run_status)
        )
        await session.commit()

    response = await retry_job(client, tenant, job, 1)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"
    async with session_factory() as session:
        current_job = await session.get(ExecutionJob, job_id)
        runs = list(
            (await session.scalars(select(ExecutionRun).where(ExecutionRun.job_id == job_id))).all()
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "execution_job.retry_reserved")
        )
    assert current_job is not None and current_job.status is job_status
    assert len(runs) == 1 and runs[0].status is run_status
    assert audit_count == 0


async def test_retry_rejects_stale_repeated_and_exhausted_attempts(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant, workspace = await setup_tenant(client, "Retry Bounds")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)

    stale = await retry_job(client, tenant, job, 2)
    first = await retry_job(client, tenant, job, 1)
    repeated = await retry_job(client, tenant, job, 1)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    second = await retry_job(client, tenant, job, 2)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    exhausted = await retry_job(client, tenant, job, 3)

    assert stale.status_code == 409
    assert first.status_code == 200
    assert repeated.status_code == 409
    assert second.status_code == 200
    assert exhausted.status_code == 409


async def test_retry_is_strict_and_tenant_scoped(client: AsyncClient) -> None:
    tenant_a, _ = await setup_tenant(client, "Retry Tenant A")
    tenant_b, workspace_b = await setup_tenant(client, "Retry Tenant B")
    job_b = await create_job(client, tenant_b, workspace_b)

    strict = await client.post(
        f"/api/v1/tenants/{tenant_b['id']}/execution-jobs/{job_b['id']}/retries",
        headers=headers(tenant_b),
        json={"expected_attempt_number": 1, "unexpected": True},
    )
    missing = await client.post(
        f"/api/v1/tenants/{tenant_a['id']}/execution-jobs/{uuid4()}/retries",
        headers=headers(tenant_a),
        json={"expected_attempt_number": 1},
    )
    cross_tenant = await retry_job(client, tenant_a, job_b, 1)

    assert strict.status_code == 422
    assert missing.status_code == 404
    assert cross_tenant.status_code == 404


async def test_retry_insert_failure_rolls_back_job_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, workspace = await setup_tenant(client, "Retry Rollback")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)

    async def fail_insert(*_args: object, **_kwargs: object) -> ExecutionRun:
        raise IntegrityError("insert", {}, Exception("forced"))

    monkeypatch.setattr(ExecutionRepository, "insert_run", fail_insert)
    response = await retry_job(client, tenant, job, 1)

    assert response.status_code == 409
    current = await client.get(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs/{job['id']}",
        headers=headers(tenant),
    )
    assert current.json()["status"] == "failed"
    assert current.json()["latest_run"]["attempt_number"] == 1
    async with session_factory() as session:
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "execution_job.retry_reserved")
        )
    assert audit_count == 0


async def test_two_competing_retry_requests_cannot_both_succeed(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, workspace = await setup_tenant(client, "Competing Retries")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)
    original_compare_and_set = ExecutionRepository.compare_and_set_job_status
    both_callers_ready = asyncio.Event()
    update_lock = asyncio.Lock()
    callers = 0

    async def synchronize_competing_callers(
        repository: ExecutionRepository,
        context: TenantContext,
        job_id: UUID,
        expected_status: ExecutionStatus,
        target_status: ExecutionStatus,
    ) -> bool:
        nonlocal callers
        callers += 1
        if callers == 2:
            both_callers_ready.set()
        await both_callers_ready.wait()
        async with update_lock:
            return await original_compare_and_set(
                repository, context, job_id, expected_status, target_status
            )

    monkeypatch.setattr(
        ExecutionRepository, "compare_and_set_job_status", synchronize_competing_callers
    )
    responses = await asyncio.gather(
        retry_job(client, tenant, job, 1),
        retry_job(client, tenant, job, 1),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    async with session_factory() as session:
        run_count = len(
            list(
                (
                    await session.scalars(
                        select(ExecutionRun).where(ExecutionRun.job_id == UUID(str(job["id"])))
                    )
                ).all()
            )
        )
    assert run_count == 2


async def test_retry_commit_failure_rolls_back_run_job_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, workspace = await setup_tenant(client, "Retry Commit Rollback")
    job = await create_job(client, tenant, workspace)
    await set_job_and_run_status(session_factory, tenant["id"], job["id"], ExecutionStatus.FAILED)

    async def fail_commit(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError("commit", {}, Exception("forced"))

    monkeypatch.setattr(ExecutionRepository, "commit", fail_commit)
    response = await retry_job(client, tenant, job, 1)

    assert response.status_code == 409
    async with session_factory() as session:
        current_job = await session.get(ExecutionJob, UUID(str(job["id"])))
        runs = list(
            (
                await session.scalars(
                    select(ExecutionRun).where(ExecutionRun.job_id == UUID(str(job["id"])))
                )
            ).all()
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "execution_job.retry_reserved")
        )
    assert current_job is not None and current_job.status is ExecutionStatus.FAILED
    assert len(runs) == 1
    assert audit_count == 0
