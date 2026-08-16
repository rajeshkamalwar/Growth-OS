from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.db.models import Workspace
from growth_os.main import create_app
from growth_os.repositories import FoundationRepository, OnboardingRecordStatus, TenantContext
from growth_os.services import FoundationService


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    app = create_app(
        readiness_probe=_ready,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api
    await engine.dispose()


async def _ready() -> None:
    return None


async def create_workspace(client: AsyncClient, name: str = "Workspace") -> tuple[str, str]:
    tenant = await client.post("/api/v1/tenants", json={"name": f"Tenant {uuid4()}"})
    tenant_id = tenant.json()["id"]
    workspace = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers={"X-Tenant-ID": tenant_id},
        json={"name": name},
    )
    return tenant_id, workspace.json()["id"]


async def create_workspace_for_tenant(client: AsyncClient, tenant_id: str, name: str) -> str:
    response = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers={"X-Tenant-ID": tenant_id},
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()["id"]


def path(tenant_id: str, workspace_id: str) -> str:
    return f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/onboarding-status"


async def add_step(client: AsyncClient, tenant_id: str, workspace_id: str, step: str) -> None:
    headers = {"X-Tenant-ID": tenant_id}
    if step == "site":
        site_token = uuid4()
        response = await client.post(
            f"/api/v1/tenants/{tenant_id}/sites",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "name": f"Site {site_token}",
                "url": f"https://{site_token}.example.com",
            },
        )
    else:
        payloads = {
            "business-profile": {"company_name": "Example"},
            "primary-growth-goal": {"objective": "Grow"},
            "autonomy-policy": {"level": "observe_only", "is_paused": True},
        }
        response = await client.post(
            f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/{step}",
            headers=headers,
            json=payloads[step],
        )
    assert response.status_code == 201


async def test_empty_and_complete_status_have_exact_contract(client: AsyncClient) -> None:
    tenant_id, workspace_id = await create_workspace(client)
    headers = {"X-Tenant-ID": tenant_id}

    empty = await client.get(path(tenant_id, workspace_id), headers=headers)
    assert empty.status_code == 200
    assert empty.json() == {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "has_site": False,
        "has_business_profile": False,
        "has_primary_growth_goal": False,
        "has_autonomy_policy": False,
        "is_foundation_complete": False,
        "missing_steps": [
            "site",
            "business_profile",
            "primary_growth_goal",
            "autonomy_policy",
        ],
    }

    for step in ("autonomy-policy", "primary-growth-goal", "site", "business-profile"):
        await add_step(client, tenant_id, workspace_id, step)

    complete = await client.get(path(tenant_id, workspace_id), headers=headers)
    assert complete.json() == {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "has_site": True,
        "has_business_profile": True,
        "has_primary_growth_goal": True,
        "has_autonomy_policy": True,
        "is_foundation_complete": True,
        "missing_steps": [],
    }


@pytest.mark.parametrize(
    ("step", "flag", "missing"),
    [
        ("site", "has_site", ["business_profile", "primary_growth_goal", "autonomy_policy"]),
        (
            "business-profile",
            "has_business_profile",
            ["site", "primary_growth_goal", "autonomy_policy"],
        ),
        (
            "primary-growth-goal",
            "has_primary_growth_goal",
            ["site", "business_profile", "autonomy_policy"],
        ),
        (
            "autonomy-policy",
            "has_autonomy_policy",
            ["site", "business_profile", "primary_growth_goal"],
        ),
    ],
)
async def test_each_individual_record_is_scoped_and_canonically_ordered(
    client: AsyncClient, step: str, flag: str, missing: list[str]
) -> None:
    tenant_id, workspace_id = await create_workspace(client)
    await add_step(client, tenant_id, workspace_id, step)

    body = (
        await client.get(path(tenant_id, workspace_id), headers={"X-Tenant-ID": tenant_id})
    ).json()
    assert body[flag] is True
    assert sum(body[name] for name in body if name.startswith("has_")) == 1
    assert body["is_foundation_complete"] is False
    assert body["missing_steps"] == missing


async def test_other_workspace_records_and_multiple_sites_do_not_distort_status(
    client: AsyncClient,
) -> None:
    tenant_id, workspace_id = await create_workspace(client, "Target")
    same_tenant_workspace_id = await create_workspace_for_tenant(client, tenant_id, "Sibling")
    other_tenant_id, other_workspace_id = await create_workspace(client, "Other")
    for step in ("site", "business-profile", "primary-growth-goal", "autonomy-policy"):
        await add_step(client, tenant_id, same_tenant_workspace_id, step)
        await add_step(client, other_tenant_id, other_workspace_id, step)
    await add_step(client, tenant_id, workspace_id, "site")
    await add_step(client, tenant_id, workspace_id, "site")

    body = (
        await client.get(path(tenant_id, workspace_id), headers={"X-Tenant-ID": tenant_id})
    ).json()
    assert body["has_site"] is True
    assert body["missing_steps"] == [
        "business_profile",
        "primary_growth_goal",
        "autonomy_policy",
    ]


async def test_mixed_status_ignores_content_policy_values_and_connector(
    client: AsyncClient,
) -> None:
    tenant_id, workspace_id = await create_workspace(client)
    headers = {"X-Tenant-ID": tenant_id}
    site_token = uuid4()
    site = await client.post(
        f"/api/v1/tenants/{tenant_id}/sites",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "name": f"Site {site_token}",
            "url": f"https://{site_token}.example.com",
        },
    )
    profile = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile",
        headers=headers,
        json={"company_name": "Sparse", "business_description": "Stored intent"},
    )
    policy = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy",
        headers=headers,
        json={"level": "low_risk_auto", "is_paused": False},
    )
    connector = await client.post(
        f"/api/v1/tenants/{tenant_id}/connector-statuses",
        headers=headers,
        json={"workspace_id": workspace_id, "site_id": site.json()["id"], "kind": "placeholder"},
    )
    assert {site.status_code, profile.status_code, policy.status_code, connector.status_code} == {
        201
    }

    body = (await client.get(path(tenant_id, workspace_id), headers=headers)).json()
    assert body["has_site"] is True
    assert body["has_business_profile"] is True
    assert body["has_primary_growth_goal"] is False
    assert body["has_autonomy_policy"] is True
    assert body["is_foundation_complete"] is False
    assert body["missing_steps"] == ["primary_growth_goal"]


async def test_parent_errors_are_structured_and_non_disclosing(client: AsyncClient) -> None:
    tenant_a, workspace_a = await create_workspace(client, "A")
    tenant_b, workspace_b = await create_workspace(client, "B")
    expected = {"error": {"code": "not_found", "message": "Resource not found"}}

    mismatch = await client.get(path(tenant_a, workspace_a), headers={"X-Tenant-ID": tenant_b})
    missing = await client.get(path(tenant_a, str(uuid4())), headers={"X-Tenant-ID": tenant_a})
    cross_tenant = await client.get(path(tenant_a, workspace_b), headers={"X-Tenant-ID": tenant_a})
    for response in (mismatch, missing, cross_tenant):
        assert response.status_code == 404
        assert response.json() == expected
        assert "has_site" not in response.text

    malformed = await client.get(path(tenant_a, "invalid"), headers={"X-Tenant-ID": tenant_a})
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "validation_error"

    missing_header = await client.get(path(tenant_a, workspace_a))
    assert missing_header.status_code == 422
    assert missing_header.json()["error"]["code"] == "validation_error"


async def test_get_creates_no_audit_event(client: AsyncClient) -> None:
    tenant_id, workspace_id = await create_workspace(client)
    headers = {"X-Tenant-ID": tenant_id}
    await add_step(client, tenant_id, workspace_id, "business-profile")
    audit_path = f"/api/v1/tenants/{tenant_id}/audit-events"
    before = await client.get(audit_path, headers=headers)

    response = await client.get(path(tenant_id, workspace_id), headers=headers)
    after = await client.get(audit_path, headers=headers)

    assert response.status_code == 200
    assert after.json() == before.json()


async def test_repository_uses_one_scoped_four_exists_projection() -> None:
    session = MagicMock()
    projected = MagicMock(
        has_site=False,
        has_business_profile=False,
        has_primary_growth_goal=False,
        has_autonomy_policy=False,
    )
    executed = MagicMock()
    executed.one.return_value = projected
    session.execute = AsyncMock(return_value=executed)
    tenant_id, workspace_id = uuid4(), uuid4()

    await FoundationRepository(session).get_onboarding_record_status(
        TenantContext(tenant_id), workspace_id
    )

    session.execute.assert_awaited_once()
    sql = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert sql.count("EXISTS (SELECT *") == 4
    for table in (
        "sites",
        "workspace_business_profiles",
        "workspace_primary_growth_goals",
        "workspace_autonomy_policies",
    ):
        assert f"FROM {table}" in sql
        assert f"{table}.tenant_id = '{tenant_id.hex}'" in sql
        assert f"{table}.workspace_id = '{workspace_id.hex}'" in sql
    assert "sites.url" not in sql
    assert "company_name" not in sql
    assert "objective" not in sql
    assert "is_paused" not in sql


async def test_service_projection_never_calls_repository_writers() -> None:
    repository = MagicMock()
    repository.get_owned = AsyncMock(return_value=Workspace())
    repository.get_onboarding_record_status = AsyncMock(
        return_value=OnboardingRecordStatus(False, True, False, True)
    )
    repository.flush = AsyncMock()
    repository.refresh = AsyncMock()
    repository.commit = AsyncMock()
    repository.rollback = AsyncMock()
    tenant_id, workspace_id = uuid4(), uuid4()

    response = await FoundationService(repository).get_onboarding_status(
        TenantContext(tenant_id), workspace_id
    )

    repository.get_owned.assert_awaited_once_with(Workspace, TenantContext(tenant_id), workspace_id)
    repository.get_onboarding_record_status.assert_awaited_once_with(
        TenantContext(tenant_id), workspace_id
    )
    repository.add.assert_not_called()
    for writer in (
        repository.flush,
        repository.refresh,
        repository.commit,
        repository.rollback,
    ):
        writer.assert_not_awaited()
    assert response.missing_steps == ["site", "primary_growth_goal"]


@pytest.mark.parametrize("method", ["post", "patch", "put", "delete"])
async def test_mutating_methods_are_not_exposed(client: AsyncClient, method: str) -> None:
    tenant_id, workspace_id = await create_workspace(client)
    response = await client.request(
        method, path(tenant_id, workspace_id), headers={"X-Tenant-ID": tenant_id}, json={}
    )
    assert response.status_code == 405


async def test_no_list_shaped_onboarding_status_route(client: AsyncClient) -> None:
    tenant_id, _workspace_id = await create_workspace(client)
    response = await client.get(
        f"/api/v1/tenants/{tenant_id}/onboarding-status",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert response.status_code == 404
