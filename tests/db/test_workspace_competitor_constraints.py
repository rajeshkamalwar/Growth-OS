import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from growth_os.db.base import Base
from growth_os.db.models import Tenant, Workspace, WorkspaceCompetitor


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

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
    schema = f"product_005_{uuid4().hex}"
    bootstrap = create_async_engine(database_url)
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"search_path": schema}}
    )
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as database_session:
            yield database_session
    finally:
        await engine.dispose()
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


async def create_workspace(
    session: AsyncSession, name: str = "Workspace"
) -> tuple[Tenant, Workspace]:
    tenant = Tenant(name=f"{name} tenant")
    workspace = Workspace(tenant_id=tenant.id, name=name)
    session.add_all([tenant, workspace])
    await session.commit()
    return tenant, workspace


def test_model_contract_has_required_constraints_and_no_redundant_index() -> None:
    table = WorkspaceCompetitor.__table__
    assert table.c.name.nullable is False and table.c.name.type.length == 200
    assert table.c.website_url.nullable is True and table.c.website_url.type.length == 2048
    assert table.c.notes.nullable is True
    assert not table.indexes
    names = {constraint.name for constraint in table.constraints}
    assert "fk_workspace_competitors_workspace_tenant" in names
    assert "uq_workspace_competitors_tenant_workspace_name" in names


async def test_database_rejects_duplicate_and_cross_tenant_ownership(session: AsyncSession) -> None:
    tenant, workspace = await create_workspace(session)
    workspace_id = workspace.id
    session.add(WorkspaceCompetitor(tenant_id=tenant.id, workspace_id=workspace.id, name="Acme"))
    await session.commit()
    session.add(WorkspaceCompetitor(tenant_id=tenant.id, workspace_id=workspace.id, name="Acme"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    other = Tenant(name="Other")
    session.add(other)
    await session.commit()
    session.add(WorkspaceCompetitor(tenant_id=other.id, workspace_id=workspace_id, name="Other"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_database_allows_same_exact_name_in_another_workspace(session: AsyncSession) -> None:
    tenant, first = await create_workspace(session)
    second = Workspace(tenant_id=tenant.id, name="Second")
    session.add(second)
    await session.commit()
    session.add_all(
        [
            WorkspaceCompetitor(tenant_id=tenant.id, workspace_id=first.id, name="Acme"),
            WorkspaceCompetitor(tenant_id=tenant.id, workspace_id=second.id, name="Acme"),
        ]
    )
    await session.commit()


@pytest.mark.parametrize("name", ["", " Acme", "Acme ", "x" * 201])
async def test_database_rejects_invalid_name(session: AsyncSession, name: str) -> None:
    tenant, workspace = await create_workspace(session)
    session.add(WorkspaceCompetitor(tenant_id=tenant.id, workspace_id=workspace.id, name=name))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.parametrize("notes", ["", " note", "note ", "x" * 4001])
async def test_database_rejects_invalid_non_null_notes(session: AsyncSession, notes: str) -> None:
    tenant, workspace = await create_workspace(session)
    session.add(
        WorkspaceCompetitor(
            tenant_id=tenant.id, workspace_id=workspace.id, name="Acme", notes=notes
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_postgresql_enforces_url_length_and_null_name(
    postgres_session: AsyncSession,
) -> None:
    tenant, workspace = await create_workspace(postgres_session)
    for name, website_url in ((None, None), ("Acme", "x" * 2049)):
        with pytest.raises(IntegrityError):
            await postgres_session.execute(
                text(
                    "INSERT INTO workspace_competitors "
                    "(id, tenant_id, workspace_id, name, website_url) "
                    "VALUES (:id, :tenant, :workspace, :name, :website_url)"
                ),
                {
                    "id": uuid4(),
                    "tenant": tenant.id,
                    "workspace": workspace.id,
                    "name": name,
                    "website_url": website_url,
                },
            )
            await postgres_session.commit()
        await postgres_session.rollback()
