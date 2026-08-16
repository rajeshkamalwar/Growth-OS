import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from growth_os.db.base import Base
from growth_os.db.models import Tenant, Workspace, WorkspaceBusinessProfile


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.fixture
async def postgres_session() -> AsyncIterator[AsyncSession]:
    database_url = os.environ.get("GROWTH_OS_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("GROWTH_OS_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("GROWTH_OS_TEST_DATABASE_URL must identify a disposable asyncpg database")

    schema = f"product_001_{uuid4().hex}"
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    bootstrap_engine = create_async_engine(database_url)
    async with bootstrap_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as database_session:
            yield database_session
    finally:
        await engine.dispose()
        async with bootstrap_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap_engine.dispose()


async def test_database_rejects_duplicate_workspace_profile(session: AsyncSession) -> None:
    tenant = Tenant(name="Tenant")
    workspace = Workspace(tenant_id=tenant.id, name="Workspace")
    session.add_all([tenant, workspace])
    await session.commit()

    session.add(
        WorkspaceBusinessProfile(
            tenant_id=tenant.id, workspace_id=workspace.id, company_name="First"
        )
    )
    await session.commit()
    session.add(
        WorkspaceBusinessProfile(
            tenant_id=tenant.id, workspace_id=workspace.id, company_name="Second"
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_database_rejects_cross_tenant_workspace_reference(session: AsyncSession) -> None:
    tenant_a = Tenant(name="A")
    tenant_b = Tenant(name="B")
    workspace_b = Workspace(tenant_id=tenant_b.id, name="Workspace B")
    session.add_all([tenant_a, tenant_b, workspace_b])
    await session.commit()

    session.add(
        WorkspaceBusinessProfile(
            tenant_id=tenant_a.id,
            workspace_id=workspace_b.id,
            company_name="Invalid",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_postgresql_rejects_duplicate_workspace_profile(
    postgres_session: AsyncSession,
) -> None:
    await test_database_rejects_duplicate_workspace_profile(postgres_session)


async def test_postgresql_rejects_cross_tenant_workspace_reference(
    postgres_session: AsyncSession,
) -> None:
    await test_database_rejects_cross_tenant_workspace_reference(postgres_session)
