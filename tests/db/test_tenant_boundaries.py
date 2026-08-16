from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from growth_os.db.base import Base
from growth_os.db.models import Site, Tenant, Workspace


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


async def test_site_can_belong_to_workspace_in_same_tenant(session: AsyncSession) -> None:
    tenant = Tenant(name="Example tenant")
    workspace = Workspace(tenant_id=tenant.id, name="Primary workspace")
    session.add_all([tenant, workspace])
    await session.commit()

    site = Site(
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        name="Main website",
        url="https://example.com",
    )
    session.add(site)

    await session.commit()

    assert site.tenant_id == workspace.tenant_id


async def test_site_cannot_reference_workspace_from_another_tenant(
    session: AsyncSession,
) -> None:
    tenant_a = Tenant(name="Tenant A")
    tenant_b = Tenant(name="Tenant B")
    workspace_b = Workspace(tenant_id=tenant_b.id, name="Tenant B workspace")
    session.add_all([tenant_a, tenant_b, workspace_b])
    await session.commit()

    cross_tenant_site = Site(
        tenant_id=tenant_a.id,
        workspace_id=workspace_b.id,
        name="Invalid website",
        url="https://invalid.example",
    )
    session.add(cross_tenant_site)

    with pytest.raises(IntegrityError):
        await session.commit()


def test_domain_identifiers_are_generated_before_persistence() -> None:
    tenant = Tenant(name="Tenant")
    workspace = Workspace(tenant_id=tenant.id, name="Workspace")
    site = Site(
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        name="Website",
        url="https://example.com",
    )

    assert isinstance(tenant.id, UUID)
    assert isinstance(workspace.id, UUID)
    assert isinstance(site.id, UUID)
