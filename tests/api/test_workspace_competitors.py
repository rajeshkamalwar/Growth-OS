from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from growth_os.db.base import Base
from growth_os.db.models import (
    ActionProposal,
    ApprovalDecision,
    AuditEvent,
    ExecutionJob,
    ExecutionRun,
    WorkspaceCompetitor,
)
from growth_os.main import create_app
from growth_os.repositories import FoundationRepository


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'competitors.db'}")

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


def collection_url(tenant_id: object, workspace_id: object) -> str:
    return f"/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors"


async def test_lifecycle_pagination_and_redacted_audits(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    actor_id = str(uuid4())
    first = await client.post(
        collection_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={
            "name": "  Acme  ",
            "website_url": "https://example.com",
            "notes": "  Main rival  ",
            "actor_id": actor_id,
        },
    )
    assert first.status_code == 201
    created = first.json()
    assert created["name"] == "Acme" and created["notes"] == "Main rival"
    assert created["website_url"] == "https://example.com/"
    assert set(created) == {
        "id",
        "tenant_id",
        "workspace_id",
        "name",
        "website_url",
        "notes",
        "created_at",
        "updated_at",
    }
    await client.post(
        collection_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"name": "Beta"},
    )
    item_url = f"{collection_url(tenant_id, workspace_id)}/{created['id']}"
    assert (await client.get(item_url, headers=headers(tenant_id))).json() == created
    updated = await client.patch(
        item_url,
        headers=headers(tenant_id),
        json={"website_url": None, "notes": None, "name": "Acme 2"},
    )
    assert updated.status_code == 200
    assert updated.json()["website_url"] is None and updated.json()["notes"] is None
    page = await client.get(
        f"{collection_url(tenant_id, workspace_id)}?limit=1&offset=1",
        headers=headers(tenant_id),
    )
    assert page.status_code == 200
    assert page.json()["pagination"] == {"limit": 1, "offset": 1, "total": 2}
    async with session_factory() as session:
        audits = list(
            (await session.scalars(select(AuditEvent).order_by(AuditEvent.created_at))).all()
        )
        counts = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (ExecutionJob, ExecutionRun, ActionProposal, ApprovalDecision)
        ]
    assert [audit.event_type for audit in audits] == [
        "workspace_competitor.created",
        "workspace_competitor.created",
        "workspace_competitor.updated",
    ]
    assert audits[0].resource_type == "workspace_competitor"
    assert audits[0].resource_id == UUID(created["id"]) and audits[0].actor_id == UUID(actor_id)
    assert audits[0].details == {
        "workspace_id": workspace_id,
        "changed_fields": ["name", "notes", "website_url"],
    }
    assert audits[2].details == {
        "workspace_id": workspace_id,
        "changed_fields": ["name", "notes", "website_url"],
    }
    assert "Acme" not in str([audit.details for audit in audits])
    assert all(count == 0 for count in counts)


async def test_list_defaults_empty_beyond_end_and_deterministic_ties(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = collection_url(tenant_id, workspace_id)
    empty = await client.get(url, headers=headers(tenant_id))
    assert empty.json() == {
        "items": [],
        "pagination": {"limit": 50, "offset": 0, "total": 0},
    }
    created = [
        (await client.post(url, headers=headers(tenant_id), json={"name": name})).json()
        for name in ("B", "A", "C")
    ]
    async with session_factory() as session:
        tied_at = datetime.fromisoformat(created[0]["created_at"])
        await session.execute(update(WorkspaceCompetitor).values(created_at=tied_at))
        await session.commit()
    expected_ids = sorted(item["id"] for item in created)
    first = await client.get(f"{url}?limit=2", headers=headers(tenant_id))
    second = await client.get(f"{url}?limit=2&offset=2", headers=headers(tenant_id))
    beyond = await client.get(f"{url}?offset=4", headers=headers(tenant_id))
    assert [item["id"] for item in first.json()["items"]] == expected_ids[:2]
    assert [item["id"] for item in second.json()["items"]] == expected_ids[2:]
    assert beyond.json() == {
        "items": [],
        "pagination": {"limit": 50, "offset": 4, "total": 3},
    }


async def test_patch_omission_preserves_nullable_fields(client: AsyncClient) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = collection_url(tenant_id, workspace_id)
    created = await client.post(
        url,
        headers=headers(tenant_id),
        json={"name": "A", "website_url": "https://example.com", "notes": "Note"},
    )
    updated = await client.patch(
        f"{url}/{created.json()['id']}", headers=headers(tenant_id), json={"name": "B"}
    )
    assert updated.json()["website_url"] == "https://example.com/"
    assert updated.json()["notes"] == "Note"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
        {"name": 1},
        {"name": "A", "website_url": "ftp://example.com"},
        {"name": "A", "website_url": "/relative"},
        {"name": "A", "notes": " "},
        {"name": "A", "website_url": "https://example.com/" + "x" * 2040},
        {"name": "A", "notes": "x" * 4001},
        {"name": "A", "actor_id": "bad"},
        {"name": "A", "unknown": True},
    ],
)
async def test_create_validation_is_strict(client: AsyncClient, payload: dict[str, object]) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    response = await client.post(
        collection_url(tenant_id, workspace_id), headers=headers(tenant_id), json=payload
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"actor_id": str(uuid4())},
        {"name": None},
        {"name": " "},
        {"notes": " "},
        {"website_url": "mailto:a@example.com"},
        {"unknown": True},
    ],
)
async def test_patch_validation_is_strict(client: AsyncClient, payload: dict[str, object]) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    created = await client.post(
        collection_url(tenant_id, workspace_id), headers=headers(tenant_id), json={"name": "A"}
    )
    response = await client.patch(
        f"{collection_url(tenant_id, workspace_id)}/{created.json()['id']}",
        headers=headers(tenant_id),
        json=payload,
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


async def test_conflict_scope_and_non_disclosure(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_a, workspace_a = await setup_workspace(client, "A")
    tenant_b, workspace_b = await setup_workspace(client, "B")
    created = await client.post(
        collection_url(tenant_a, workspace_a), headers=headers(tenant_a), json={"name": "Acme"}
    )
    duplicate = await client.post(
        collection_url(tenant_a, workspace_a), headers=headers(tenant_a), json={"name": "Acme"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"error": {"code": "conflict", "message": "Resource already exists"}}
    assert "unique" not in duplicate.text.lower()
    allowed = await client.post(
        collection_url(tenant_b, workspace_b), headers=headers(tenant_b), json={"name": "Acme"}
    )
    assert allowed.status_code == 201
    expected = {"error": {"code": "not_found", "message": "Resource not found"}}
    competitor_id = created.json()["id"]
    for url, header in (
        (f"{collection_url(tenant_b, workspace_b)}/{competitor_id}", tenant_b),
        (f"{collection_url(tenant_a, workspace_b)}/{competitor_id}", tenant_a),
        (f"{collection_url(tenant_a, workspace_a)}/{competitor_id}", tenant_b),
        (f"{collection_url(tenant_a, workspace_a)}/{uuid4()}", tenant_a),
    ):
        response = await client.get(url, headers=headers(header))
        assert response.status_code == 404 and response.json() == expected
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceCompetitor)) == 2
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 2


async def test_same_name_is_allowed_in_another_workspace_of_same_tenant(
    client: AsyncClient,
) -> None:
    tenant_id, first_workspace = await setup_workspace(client)
    second = await client.post(
        f"/api/v1/tenants/{tenant_id}/workspaces",
        headers=headers(tenant_id),
        json={"name": "Second"},
    )
    for workspace_id in (first_workspace, second.json()["id"]):
        response = await client.post(
            collection_url(tenant_id, workspace_id),
            headers=headers(tenant_id),
            json={"name": "Acme"},
        )
        assert response.status_code == 201


async def test_all_methods_preserve_workspace_and_competitor_non_disclosure(
    client: AsyncClient,
) -> None:
    tenant_a, workspace_a = await setup_workspace(client, "A")
    tenant_b, workspace_b = await setup_workspace(client, "B")
    created = await client.post(
        collection_url(tenant_a, workspace_a),
        headers=headers(tenant_a),
        json={"name": "A"},
    )
    expected = {"error": {"code": "not_found", "message": "Resource not found"}}
    competitor_id = created.json()["id"]
    cases = (
        ("post", collection_url(tenant_a, workspace_b), tenant_a, {"name": "X"}),
        ("get", collection_url(tenant_a, workspace_b), tenant_a, None),
        (
            "patch",
            f"{collection_url(tenant_b, workspace_b)}/{competitor_id}",
            tenant_b,
            {"name": "X"},
        ),
        ("patch", f"{collection_url(tenant_a, workspace_a)}/{uuid4()}", tenant_a, {"name": "X"}),
    )
    for method, url, header, payload in cases:
        kwargs: dict[str, object] = {"headers": headers(header)}
        if payload is not None:
            kwargs["json"] = payload
        response = await getattr(client, method)(url, **kwargs)
        assert response.status_code == 404 and response.json() == expected


async def test_catalog_does_not_call_network_or_change_approval_semantics(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)

    def reject_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("competitor catalog attempted network access")

    monkeypatch.setattr("socket.getaddrinfo", reject_network)
    created = await client.post(
        collection_url(tenant_id, workspace_id),
        headers=headers(tenant_id),
        json={"name": "A", "website_url": "https://example.com"},
    )
    assert created.status_code == 201
    job = await client.post(
        f"/api/v1/tenants/{tenant_id}/execution-jobs",
        headers=headers(tenant_id),
        json={
            "workspace_id": workspace_id,
            "kind": "site_analysis",
            "idempotency_key": "competitor-non-enforcement",
        },
    )
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


async def test_conflicting_rename_rolls_back_without_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = collection_url(tenant_id, workspace_id)
    first = await client.post(url, headers=headers(tenant_id), json={"name": "A"})
    await client.post(url, headers=headers(tenant_id), json={"name": "B"})
    response = await client.patch(
        f"{url}/{first.json()['id']}", headers=headers(tenant_id), json={"name": "B"}
    )
    assert response.status_code == 409
    fetched = await client.get(f"{url}/{first.json()['id']}", headers=headers(tenant_id))
    assert fetched.json()["name"] == "A"
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 2


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=x"])
async def test_pagination_validation(client: AsyncClient, query: str) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    response = await client.get(
        f"{collection_url(tenant_id, workspace_id)}?{query}", headers=headers(tenant_id)
    )
    assert response.status_code == 422


@pytest.mark.parametrize("failure_method", ["flush", "commit"])
async def test_persistence_failures_roll_back_competitor_and_audit(
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
        collection_url(tenant_id, workspace_id), headers=headers(tenant_id), json={"name": "A"}
    )
    assert response.status_code == 500
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceCompetitor)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize("failure_method", ["flush", "commit"])
async def test_update_failures_restore_competitor_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    failure_method: str,
) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = collection_url(tenant_id, workspace_id)
    created = await client.post(url, headers=headers(tenant_id), json={"name": "A"})

    async def fail(_self) -> None:
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(FoundationRepository, failure_method, fail)
    response = await client.patch(
        f"{url}/{created.json()['id']}", headers=headers(tenant_id), json={"name": "B"}
    )
    assert response.status_code == 500
    async with session_factory() as session:
        competitor = await session.scalar(select(WorkspaceCompetitor))
        assert competitor is not None and competitor.name == "A"
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_unsupported_routes_do_not_exist(client: AsyncClient) -> None:
    tenant_id, workspace_id = await setup_workspace(client)
    url = collection_url(tenant_id, workspace_id)
    assert (await client.delete(f"{url}/{uuid4()}", headers=headers(tenant_id))).status_code == 405
    assert (await client.put(f"{url}/{uuid4()}", headers=headers(tenant_id))).status_code == 405
    assert (
        await client.get(f"/api/v1/tenants/{tenant_id}/competitors", headers=headers(tenant_id))
    ).status_code == 404
