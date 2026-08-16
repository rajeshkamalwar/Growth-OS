import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.db.models import AuditEvent, WorkspaceBusinessProfile
from growth_os.main import create_app
from growth_os.repositories import FoundationRepository


@pytest.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profiles.db'}")

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
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(readiness_probe=_ready, session_factory=session_factory)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


async def _ready() -> None:
    return None


def headers(tenant_id: object) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


async def setup_workspace(client: AsyncClient, name: str = "Tenant") -> tuple[str, str]:
    tenant_response = await client.post("/api/v1/tenants", json={"name": name})
    tenant_id = tenant_response.json()["id"]
    workspace_response = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers=headers(tenant_id),
        json={"name": "Primary"},
    )
    return tenant_id, workspace_response.json()["id"]


def profile_url(tenant_id: object, workspace_id: object) -> str:
    return f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile"


async def test_profile_lifecycle_is_partial_stable_and_audited(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    actor_id = str(uuid4())
    create_response = await client.post(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={
            "company_name": " Acme Growth ",
            "business_description": "Confidential operating context",
            "actor_id": actor_id,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["company_name"] == "Acme Growth"
    assert created["business_description"] == "Confidential operating context"
    assert created["products_services"] is None
    assert set(created) == {
        "id",
        "tenant_id",
        "workspace_id",
        "company_name",
        "business_description",
        "products_services",
        "target_audience",
        "positioning",
        "brand_voice",
        "created_at",
        "updated_at",
    }

    get_response = await client.get(
        profile_url(tenant_id, workspace_id), headers=headers(tenant_id)
    )
    assert get_response.status_code == 200
    assert get_response.json() == created

    patch_response = await client.patch(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"products_services": "Advisory", "business_description": None},
    )
    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["company_name"] == "Acme Growth"
    assert updated["products_services"] == "Advisory"
    assert updated["business_description"] is None

    async with session_factory() as session:
        events = list((await session.scalars(select(AuditEvent))).all())
    by_type = {event.event_type: event for event in events}
    assert set(by_type) == {
        "workspace_business_profile.created",
        "workspace_business_profile.updated",
    }
    created_event = by_type["workspace_business_profile.created"]
    updated_event = by_type["workspace_business_profile.updated"]
    assert created_event.actor_id == UUID(actor_id)
    assert updated_event.actor_id is None
    assert created_event.details == {
        "workspace_id": workspace_id,
        "changed_fields": ["business_description", "company_name"],
    }
    assert updated_event.details == {
        "workspace_id": workspace_id,
        "changed_fields": ["business_description", "products_services"],
    }
    assert "Confidential" not in str([event.details for event in events])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"company_name": ""},
        {"company_name": "   "},
        {"company_name": "x" * 201},
        {"company_name": "Acme", "brand_voice": "x" * 4001},
        {"company_name": "Acme", "unknown": "field"},
    ],
)
async def test_create_validation_is_strict(client: AsyncClient, payload: dict[str, object]) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    response = await client.post(
        profile_url(tenant_id, workspace_id), headers=headers(tenant_id), json=payload
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"actor_id": str(uuid4())},
        {"company_name": None},
        {"company_name": " "},
        {"positioning": "x" * 4001},
        {"unexpected": "field"},
    ],
)
async def test_patch_validation_requires_a_real_profile_change(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    await client.post(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"company_name": "Acme"},
    )
    response = await client.patch(
        profile_url(tenant_id, workspace_id), headers=headers(tenant_id), json=payload
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_duplicate_and_concurrent_creation_conflict_without_extra_audits(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = profile_url(tenant_id, workspace_id)
    responses = await asyncio.gather(
        client.post(url, headers=headers(tenant_id), json={"company_name": "One"}),
        client.post(url, headers=headers(tenant_id), json={"company_name": "Two"}),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]

    duplicate = await client.post(url, headers=headers(tenant_id), json={"company_name": "Three"})
    assert duplicate.status_code == 409
    assert duplicate.json() == {"error": {"code": "conflict", "message": "Resource already exists"}}

    async with session_factory() as session:
        profile_count = await session.scalar(
            select(func.count()).select_from(WorkspaceBusinessProfile)
        )
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert profile_count == 1
    assert audit_count == 1


async def test_missing_and_cross_tenant_access_is_indistinguishable(client: AsyncClient) -> None:
    tenant_a, workspace_a = await setup_workspace(client, "A")
    tenant_b, workspace_b = await setup_workspace(client, "B")
    await client.post(
        profile_url(tenant_b, workspace_b),
        headers=headers(tenant_b),
        json={"company_name": "Private"},
    )
    missing_workspace = str(uuid4())
    expected = {"error": {"code": "not_found", "message": "Resource not found"}}

    for method, payload in (("get", None), ("patch", {"brand_voice": "X"})):
        for workspace_id in (missing_workspace, workspace_b, workspace_a):
            response = await client.request(
                method,
                profile_url(tenant_a, workspace_id),
                headers=headers(tenant_a),
                json=payload,
            )
            assert response.status_code == 404
            assert response.json() == expected

    for workspace_id in (missing_workspace, workspace_b):
        response = await client.post(
            profile_url(tenant_a, workspace_id),
            headers=headers(tenant_a),
            json={"company_name": "X"},
        )
        assert response.status_code == 404
        assert response.json() == expected


async def test_failed_access_and_mutations_do_not_add_audits(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    await client.post(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"company_name": "Acme"},
    )
    await client.get(profile_url(tenant_id, workspace_id), headers=headers(tenant_id))
    await client.patch(profile_url(tenant_id, workspace_id), headers=headers(tenant_id), json={})
    await client.post(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"company_name": "Duplicate"},
    )

    async with session_factory() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert audit_count == 1


async def test_failed_commit_rolls_back_profile_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)

    async def fail_commit(_repository: FoundationRepository) -> None:
        raise RuntimeError("forced failure")

    monkeypatch.setattr(FoundationRepository, "commit", fail_commit)
    response = await client.post(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"company_name": "Must Roll Back"},
    )
    assert response.status_code == 500

    async with session_factory() as session:
        profile_count = await session.scalar(
            select(func.count()).select_from(WorkspaceBusinessProfile)
        )
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert profile_count == 0
    assert audit_count == 0


async def test_failed_update_rolls_back_changes_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    created = await client.post(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"company_name": "Original"},
    )
    profile_id = UUID(created.json()["id"])

    async def fail_commit(_repository: FoundationRepository) -> None:
        raise RuntimeError("forced failure")

    monkeypatch.setattr(FoundationRepository, "commit", fail_commit)
    response = await client.patch(
        profile_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"company_name": "Changed"},
    )
    assert response.status_code == 500

    async with session_factory() as session:
        profile = await session.get(WorkspaceBusinessProfile, profile_id)
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert profile is not None
    assert profile.company_name == "Original"
    assert audit_count == 1
