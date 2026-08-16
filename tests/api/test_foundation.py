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
    app = create_app(readiness_probe=lambda: _ready(), session_factory=session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client

    await engine.dispose()


async def _ready() -> None:
    return None


async def create_tenant(client: AsyncClient, name: str = "Tenant") -> dict[str, object]:
    response = await client.post("/api/v1/tenants", json={"name": name})
    assert response.status_code == 201
    return response.json()


def tenant_headers(tenant_id: object) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


async def create_workspace(
    client: AsyncClient, tenant_id: object, name: str = "Workspace"
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers=tenant_headers(tenant_id),
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


async def create_site(
    client: AsyncClient, tenant_id: object, workspace_id: object
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/tenants/{tenant_id}/sites",
        headers=tenant_headers(tenant_id),
        json={
            "workspace_id": str(workspace_id),
            "name": "Main site",
            "url": "https://example.com",
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_tenant_and_workspace_happy_path_is_auditable(client: AsyncClient) -> None:
    tenant = await create_tenant(client)
    workspace = await create_workspace(client, tenant["id"])

    response = await client.patch(
        f"/api/v1/tenants/{tenant['id']}/workspaces/{workspace['id']}",
        headers=tenant_headers(tenant["id"]),
        json={"name": "Renamed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant["id"]
    assert body["name"] == "Renamed"
    assert body["id"] == workspace["id"]
    assert body["created_at"]
    assert body["updated_at"]


async def test_cross_tenant_read_and_mutation_fail_safely(client: AsyncClient) -> None:
    tenant_a = await create_tenant(client, "Tenant A")
    tenant_b = await create_tenant(client, "Tenant B")
    workspace_b = await create_workspace(client, tenant_b["id"])

    read_response = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}/workspaces/{workspace_b['id']}",
        headers=tenant_headers(tenant_a["id"]),
    )
    update_response = await client.patch(
        f"/api/v1/tenants/{tenant_a['id']}/workspaces/{workspace_b['id']}",
        headers=tenant_headers(tenant_a["id"]),
        json={"name": "Stolen"},
    )

    expected = {"error": {"code": "not_found", "message": "Resource not found"}}
    assert read_response.status_code == 404
    assert read_response.json() == expected
    assert update_response.status_code == 404
    assert update_response.json() == expected


async def test_tenant_header_must_match_path(client: AsyncClient) -> None:
    tenant_a = await create_tenant(client, "Tenant A")
    tenant_b = await create_tenant(client, "Tenant B")

    response = await client.get(
        f"/api/v1/tenants/{tenant_a['id']}", headers=tenant_headers(tenant_b["id"])
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_validation_errors_use_structured_safe_shape(client: AsyncClient) -> None:
    tenant = await create_tenant(client)

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/workspaces",
        headers=tenant_headers(tenant["id"]),
        json={"name": ""},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed"
    assert "traceback" not in str(body).lower()


async def test_duplicate_workspace_returns_conflict_without_database_details(
    client: AsyncClient,
) -> None:
    tenant = await create_tenant(client)
    await create_workspace(client, tenant["id"], "Duplicate")

    response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/workspaces",
        headers=tenant_headers(tenant["id"]),
        json={"name": "Duplicate"},
    )

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "conflict", "message": "Resource already exists"}}
    assert "unique" not in response.text.lower()


async def test_collections_are_paginated_and_tenant_scoped(client: AsyncClient) -> None:
    tenant = await create_tenant(client)
    await create_workspace(client, tenant["id"], "One")
    await create_workspace(client, tenant["id"], "Two")

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/workspaces?limit=1&offset=1",
        headers=tenant_headers(tenant["id"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["pagination"] == {"limit": 1, "offset": 1, "total": 2}


async def test_site_membership_and_connector_status_control_plane_paths(
    client: AsyncClient,
) -> None:
    tenant = await create_tenant(client)
    workspace = await create_workspace(client, tenant["id"])
    site = await create_site(client, tenant["id"], workspace["id"])
    headers = tenant_headers(tenant["id"])

    membership_response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/memberships",
        headers=headers,
        json={"workspace_id": workspace["id"], "user_id": str(uuid4()), "role": "member"},
    )
    connector_response = await client.post(
        f"/api/v1/tenants/{tenant['id']}/connector-statuses",
        headers=headers,
        json={"workspace_id": workspace["id"], "site_id": site["id"], "kind": "placeholder"},
    )

    assert membership_response.status_code == 201
    assert membership_response.json()["role"] == "member"
    assert connector_response.status_code == 201
    connector = connector_response.json()
    assert connector["status"] == "not_configured"
    assert set(connector) == {
        "id",
        "tenant_id",
        "workspace_id",
        "site_id",
        "kind",
        "status",
        "created_at",
        "updated_at",
    }


async def test_cross_tenant_parent_ids_cannot_create_children(client: AsyncClient) -> None:
    tenant_a = await create_tenant(client, "Tenant A")
    tenant_b = await create_tenant(client, "Tenant B")
    workspace_b = await create_workspace(client, tenant_b["id"])

    response = await client.post(
        f"/api/v1/tenants/{tenant_a['id']}/sites",
        headers=tenant_headers(tenant_a["id"]),
        json={
            "workspace_id": workspace_b["id"],
            "name": "Cross tenant",
            "url": "https://cross.example",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_missing_resource_returns_structured_not_found(client: AsyncClient) -> None:
    tenant = await create_tenant(client)

    response = await client.get(
        f"/api/v1/tenants/{tenant['id']}/sites/{uuid4()}",
        headers=tenant_headers(tenant["id"]),
    )

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Resource not found"}}
