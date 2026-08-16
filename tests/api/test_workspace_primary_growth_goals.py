import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.db.models import AuditEvent, WorkspacePrimaryGrowthGoal
from growth_os.main import create_app
from growth_os.repositories import FoundationRepository


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'goals.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
    response = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers=headers(tenant_id),
        json={"name": "Primary"},
    )
    return tenant_id, response.json()["id"]


def goal_url(tenant_id: object, workspace_id: object) -> str:
    return f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/primary-growth-goal"


async def test_goal_lifecycle_is_partial_stable_and_audited(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    actor_id = str(uuid4())
    response = await client.post(
        goal_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={
            "objective": " Grow qualified pipeline ",
            "success_definition": "Supplied intent",
            "target_date": "2027-01-31",
            "actor_id": actor_id,
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["objective"] == "Grow qualified pipeline"
    assert created["target_date"] == "2027-01-31"
    assert set(created) == {
        "id",
        "tenant_id",
        "workspace_id",
        "objective",
        "success_definition",
        "target_date",
        "created_at",
        "updated_at",
    }
    assert (
        await client.get(goal_url(tenant_id, workspace_id), headers=headers(tenant_id))
    ).json() == created
    patched = await client.patch(
        goal_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"success_definition": None, "target_date": None},
    )
    assert patched.status_code == 200
    assert patched.json()["id"] == created["id"]
    assert patched.json()["created_at"] == created["created_at"]
    assert patched.json()["updated_at"] >= created["updated_at"]
    assert patched.json()["objective"] == created["objective"]
    assert patched.json()["success_definition"] is None and patched.json()["target_date"] is None
    async with session_factory() as session:
        events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_type == "workspace_primary_growth_goal"
                    )
                )
            ).all()
        )
    assert [event.event_type for event in events] == [
        "workspace_primary_growth_goal.created",
        "workspace_primary_growth_goal.updated",
    ]
    assert events[0].actor_id == UUID(actor_id)
    assert events[0].details == {
        "workspace_id": workspace_id,
        "changed_fields": ["objective", "success_definition", "target_date"],
    }
    assert events[1].details == {
        "workspace_id": workspace_id,
        "changed_fields": ["success_definition", "target_date"],
    }
    assert all(event.resource_id == UUID(created["id"]) for event in events)
    audit_details = str([event.details for event in events])
    assert "Grow qualified pipeline" not in audit_details
    assert "Supplied intent" not in audit_details
    assert "2027-01-31" not in audit_details


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"objective": None},
        {"objective": ""},
        {"objective": "   "},
        {"objective": "x" * 2001},
        {"objective": "X", "success_definition": " "},
        {"objective": "X", "success_definition": "x" * 2001},
        {"objective": "X", "target_date": "2026-02-30"},
        {"objective": "X", "target_date": "2026-01-01T00:00:00Z"},
        {"objective": "X", "target_date": 0},
        {"objective": "X", "actor_id": "bad"},
        {"objective": "X", "unknown": True},
    ],
)
async def test_create_validation_is_strict(client: AsyncClient, payload: dict[str, object]) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    response = await client.post(
        goal_url(tenant_id, workspace_id), headers=headers(tenant_id), json=payload
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"actor_id": str(uuid4())},
        {"objective": None},
        {"objective": " "},
        {"objective": "x" * 2001},
        {"success_definition": " "},
        {"success_definition": "x" * 2001},
        {"target_date": "not-a-date"},
        {"target_date": "2026-01-01T00:00:00Z"},
        {"target_date": 0},
        {"objective": "X", "actor_id": "bad"},
        {"unexpected": True},
    ],
)
async def test_patch_validation_requires_goal_change(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    await client.post(
        goal_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"objective": "Original"},
    )
    response = await client.patch(
        goal_url(tenant_id, workspace_id), headers=headers(tenant_id), json=payload
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


async def test_duplicate_concurrent_creation_conflicts_without_extra_audits(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = goal_url(tenant_id, workspace_id)
    responses = await asyncio.gather(
        *(
            client.post(url, headers=headers(tenant_id), json={"objective": value})
            for value in ("One", "Two")
        )
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    duplicate = await client.post(url, headers=headers(tenant_id), json={"objective": "Three"})
    assert duplicate.status_code == 409 and duplicate.json() == {
        "error": {"code": "conflict", "message": "Resource already exists"}
    }
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(WorkspacePrimaryGrowthGoal)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_missing_cross_tenant_and_header_mismatch_are_not_found(client: AsyncClient) -> None:
    tenant_a, workspace_a = await setup_workspace(client, "A")
    tenant_b, workspace_b = await setup_workspace(client, "B")
    await client.post(
        goal_url(tenant_b, workspace_b), headers=headers(tenant_b), json={"objective": "Private"}
    )
    expected = {"error": {"code": "not_found", "message": "Resource not found"}}
    for method, payload in (
        ("get", None),
        ("patch", {"objective": "X"}),
        ("post", {"objective": "X"}),
    ):
        for workspace_id in (str(uuid4()), workspace_b):
            response = await client.request(
                method, goal_url(tenant_a, workspace_id), headers=headers(tenant_a), json=payload
            )
            assert response.status_code == 404 and response.json() == expected
    for method, payload in (("get", None), ("patch", {"objective": "X"})):
        response = await client.request(
            method,
            goal_url(tenant_a, workspace_a),
            headers=headers(tenant_a),
            json=payload,
        )
        assert response.status_code == 404 and response.json() == expected
    response = await client.get(goal_url(tenant_a, workspace_a), headers=headers(tenant_b))
    assert response.status_code == 404 and response.json() == expected


async def test_reads_failures_and_unsupported_routes_do_not_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = goal_url(tenant_id, workspace_id)
    await client.post(url, headers=headers(tenant_id), json={"objective": "Intent"})
    assert (await client.get(url, headers=headers(tenant_id))).status_code == 200
    assert (await client.patch(url, headers=headers(tenant_id), json={})).status_code == 422
    assert (await client.delete(url, headers=headers(tenant_id))).status_code == 405
    assert (
        await client.get(
            f"/api/v1/tenants/{tenant_id}/primary-growth-goals", headers=headers(tenant_id)
        )
    ).status_code == 404
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_forced_create_and_update_failures_roll_back_state_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = goal_url(tenant_id, workspace_id)

    async def fail_transaction(_repository: FoundationRepository) -> None:
        raise RuntimeError("forced")

    monkeypatch.setattr(FoundationRepository, "flush", fail_transaction)
    assert (
        await client.post(url, headers=headers(tenant_id), json={"objective": "Nope"})
    ).status_code == 500
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(WorkspacePrimaryGrowthGoal)) == 0
        )
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0
    monkeypatch.undo()
    created = await client.post(url, headers=headers(tenant_id), json={"objective": "Original"})
    monkeypatch.setattr(FoundationRepository, "commit", fail_transaction)
    assert (
        await client.patch(url, headers=headers(tenant_id), json={"objective": "Changed"})
    ).status_code == 500
    async with session_factory() as session:
        goal = await session.get(WorkspacePrimaryGrowthGoal, UUID(created.json()["id"]))
        assert goal is not None and goal.objective == "Original"
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1
