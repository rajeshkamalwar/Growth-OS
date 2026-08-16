import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.db.models import (
    ActionProposal,
    ApprovalDecision,
    AuditEvent,
    ExecutionJob,
    ExecutionRun,
    WorkspaceAutonomyPolicy,
)
from growth_os.main import create_app
from growth_os.repositories import FoundationRepository


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'autonomy.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    app = create_app(readiness_probe=_ready, session_factory=session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as api_client:
        yield api_client


async def _ready() -> None:
    return None


def headers(tenant_id: object) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


async def setup_workspace(client: AsyncClient, name: str = "Tenant") -> tuple[str, str]:
    tenant_id = (await client.post("/api/v1/tenants", json={"name": name})).json()["id"]
    workspace = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers=headers(tenant_id),
        json={"name": "Primary"},
    )
    return tenant_id, workspace.json()["id"]


def policy_url(tenant_id: object, workspace_id: object) -> str:
    return f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy"


async def test_lifecycle_defaults_paused_and_writes_redacted_audits(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    actor_id = str(uuid4())
    response = await client.post(
        policy_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"level": "observe_only", "actor_id": actor_id},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["is_paused"] is True
    assert set(created) == {
        "id",
        "created_at",
        "updated_at",
        "tenant_id",
        "workspace_id",
        "level",
        "is_paused",
    }
    fetched = await client.get(policy_url(tenant_id, workspace_id), headers=headers(tenant_id))
    assert fetched.json() == created
    updated = await client.patch(
        policy_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"is_paused": False, "level": "low_risk_auto"},
    )
    assert updated.status_code == 200
    assert updated.json()["is_paused"] is False
    assert updated.json()["level"] == "low_risk_auto"
    async with session_factory() as session:
        audits = list((await session.scalars(select(AuditEvent))).all())
        side_effect_counts = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (ExecutionJob, ExecutionRun, ActionProposal, ApprovalDecision)
        ]
    assert [audit.event_type for audit in audits] == [
        "workspace_autonomy_policy.created",
        "workspace_autonomy_policy.updated",
    ]
    assert audits[0].resource_type == "workspace_autonomy_policy"
    assert audits[0].resource_id == UUID(created["id"])
    assert audits[0].actor_id == UUID(actor_id)
    assert audits[0].details == {"workspace_id": workspace_id, "changed_fields": ["level"]}
    assert audits[1].details == {
        "workspace_id": workspace_id,
        "changed_fields": ["is_paused", "level"],
    }
    assert "observe_only" not in str([audit.details for audit in audits])
    assert "low_risk_auto" not in str([audit.details for audit in audits])
    assert all(count == 0 for count in side_effect_counts)


async def test_explicit_create_pause_is_audited_as_supplied(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    response = await client.post(
        policy_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"level": "approval_required", "is_paused": False},
    )
    assert response.status_code == 201 and response.json()["is_paused"] is False
    async with session_factory() as session:
        audit = await session.scalar(select(AuditEvent))
    assert audit is not None
    assert audit.details == {
        "workspace_id": workspace_id,
        "changed_fields": ["is_paused", "level"],
    }


@pytest.mark.parametrize("is_paused", [True, False])
@pytest.mark.parametrize(
    "level", ["observe_only", "recommend_only", "approval_required", "low_risk_auto"]
)
async def test_all_levels_and_pause_values_are_stored_preferences(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    level: str,
    is_paused: bool,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client, f"{level}-{is_paused}")
    response = await client.post(
        policy_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"level": level, "is_paused": is_paused},
    )
    assert response.status_code == 201
    assert response.json()["level"] == level
    assert response.json()["is_paused"] is is_paused
    async with session_factory() as session:
        for model in (ExecutionJob, ExecutionRun, ActionProposal, ApprovalDecision):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_policy_does_not_weaken_high_risk_approval_requirement(client: AsyncClient) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    await client.post(
        policy_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"level": "low_risk_auto", "is_paused": False},
    )
    job = await client.post(
        f"/api/v1/tenants/{tenant_id}/execution-jobs",
        headers=headers(tenant_id),
        json={
            "workspace_id": workspace_id,
            "kind": "site_analysis",
            "idempotency_key": "policy-non-enforcement",
        },
    )
    assert job.status_code == 201
    proposal = await client.post(
        f"/api/v1/tenants/{tenant_id}/action-proposals",
        headers=headers(tenant_id),
        json={
            "job_id": job.json()["id"],
            "action_type": "website_change",
            "description": "High-risk change",
            "risk_level": "high",
            "requires_approval": False,
        },
    )
    assert proposal.status_code == 422
    assert proposal.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"level": None},
        {"level": "invalid"},
        {"level": 1},
        {"level": "observe_only", "is_paused": None},
        {"level": "observe_only", "is_paused": 0},
        {"level": "observe_only", "is_paused": 1},
        {"level": "observe_only", "is_paused": "true"},
        {"level": "observe_only", "actor_id": "bad"},
        {"level": "observe_only", "unknown": True},
    ],
)
async def test_create_validation_is_strict(client: AsyncClient, payload: dict[str, object]) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    response = await client.post(
        policy_url(tenant_id, workspace_id), headers=headers(tenant_id), json=payload
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"actor_id": str(uuid4())},
        {"level": None},
        {"level": "invalid"},
        {"is_paused": None},
        {"is_paused": 0},
        {"is_paused": "false"},
        {"level": "observe_only", "actor_id": "bad"},
        {"unknown": True},
    ],
)
async def test_patch_requires_non_null_policy_change(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = policy_url(tenant_id, workspace_id)
    await client.post(url, headers=headers(tenant_id), json={"level": "observe_only"})
    response = await client.patch(url, headers=headers(tenant_id), json=payload)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


async def test_concurrent_create_conflicts_without_extra_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = policy_url(tenant_id, workspace_id)
    responses = await asyncio.gather(
        *[
            client.post(url, headers=headers(tenant_id), json={"level": "observe_only"})
            for _ in range(2)
        ]
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json() == {"error": {"code": "conflict", "message": "Resource already exists"}}
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceAutonomyPolicy)) == 1
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_tenant_non_disclosure_and_missing_resources(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_a, workspace_a = await setup_workspace(client, "A")
    tenant_b, workspace_b = await setup_workspace(client, "B")
    await client.post(
        policy_url(tenant_a, workspace_a),
        headers=headers(tenant_a),
        json={"level": "observe_only"},
    )
    expected = {"error": {"code": "not_found", "message": "Resource not found"}}
    cases = (
        ("get", tenant_b, workspace_a, tenant_b),
        ("patch", tenant_b, workspace_a, tenant_b),
        ("post", tenant_a, workspace_b, tenant_a),
        ("get", tenant_a, workspace_a, tenant_b),
        ("get", tenant_a, uuid4(), tenant_a),
    )
    for method, tenant_id, workspace_id, header_id in cases:
        kwargs: dict[str, object] = {"headers": headers(header_id)}
        if method != "get":
            kwargs["json"] = {"level": "recommend_only"}
        response = await getattr(client, method)(policy_url(tenant_id, workspace_id), **kwargs)
        assert response.status_code == 404 and response.json() == expected
    async with session_factory() as session:
        policies = list((await session.scalars(select(WorkspaceAutonomyPolicy))).all())
        assert len(policies) == 1
        assert policies[0].level.value == "observe_only" and policies[0].is_paused is True
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_missing_policy_and_unsupported_routes(client: AsyncClient) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = policy_url(tenant_id, workspace_id)
    assert (await client.get(url, headers=headers(tenant_id))).status_code == 404
    patch = await client.patch(url, headers=headers(tenant_id), json={"level": "recommend_only"})
    assert patch.status_code == 404
    assert (await client.delete(url, headers=headers(tenant_id))).status_code == 405
    list_url = f"/api/v1/tenants/{tenant_id}/autonomy-policies"
    assert (await client.get(list_url, headers=headers(tenant_id))).status_code == 404


async def test_get_and_failed_validation_are_audit_read_only(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = policy_url(tenant_id, workspace_id)
    await client.post(url, headers=headers(tenant_id), json={"level": "observe_only"})
    assert (await client.get(url, headers=headers(tenant_id))).status_code == 200
    assert (await client.patch(url, headers=headers(tenant_id), json={})).status_code == 422
    invalid_path = policy_url(tenant_id, "not-a-uuid")
    assert (await client.get(invalid_path, headers=headers(tenant_id))).status_code == 422
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


@pytest.mark.parametrize("failure_method", ["flush", "commit"])
async def test_persistence_failures_roll_back_policy_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    failure_method: str,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)

    async def fail(_self) -> None:
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(FoundationRepository, failure_method, fail)
    response = await client.post(
        policy_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"level": "observe_only"},
    )
    assert response.status_code == 500
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceAutonomyPolicy)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize("failure_method", ["flush", "commit"])
async def test_update_persistence_failures_restore_policy_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    failure_method: str,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = policy_url(tenant_id, workspace_id)
    await client.post(url, headers=headers(tenant_id), json={"level": "observe_only"})

    async def fail(_self) -> None:
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(FoundationRepository, failure_method, fail)
    response = await client.patch(
        url, headers=headers(tenant_id), json={"level": "low_risk_auto", "is_paused": False}
    )
    assert response.status_code == 500
    async with session_factory() as session:
        policy = await session.scalar(select(WorkspaceAutonomyPolicy))
        assert policy is not None
        assert policy.level.value == "observe_only" and policy.is_paused is True
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1
