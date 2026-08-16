from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(readiness_probe=_ready, session_factory=session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api_client:
        yield api_client
    await engine.dispose()


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
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/execution-jobs",
        headers=headers(tenant),
        json={
            "workspace_id": workspace["id"],
            "kind": "site_analysis",
            "idempotency_key": key,
            "max_attempts": 3,
        },
    )
    assert response.status_code == 201
    return response.json()


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
