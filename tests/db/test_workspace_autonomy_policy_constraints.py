import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from growth_os.db.base import Base
from growth_os.db.models import AutonomyLevel, Tenant, Workspace, WorkspaceAutonomyPolicy


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
    schema = f"product_003_{uuid4().hex}"
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"search_path": schema}}
    )
    bootstrap = create_async_engine(database_url)
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


async def create_workspace(session: AsyncSession) -> tuple[Tenant, Workspace]:
    tenant = Tenant(name="Tenant")
    workspace = Workspace(tenant_id=tenant.id, name="Workspace")
    session.add_all([tenant, workspace])
    await session.commit()
    return tenant, workspace


def test_model_contract_has_safe_default_and_no_redundant_index() -> None:
    table = WorkspaceAutonomyPolicy.__table__
    assert list(AutonomyLevel) == [
        AutonomyLevel.OBSERVE_ONLY,
        AutonomyLevel.RECOMMEND_ONLY,
        AutonomyLevel.APPROVAL_REQUIRED,
        AutonomyLevel.LOW_RISK_AUTO,
    ]
    assert table.c.is_paused.nullable is False
    assert table.c.is_paused.default.arg is True
    assert str(table.c.is_paused.server_default.arg).lower() == "true"
    assert table.c.level.nullable is False
    assert not table.indexes
    assert WorkspaceAutonomyPolicy(level=AutonomyLevel.OBSERVE_ONLY).is_paused is True


async def test_database_rejects_duplicate_and_cross_tenant_policy(session: AsyncSession) -> None:
    tenant, workspace = await create_workspace(session)
    workspace_id = workspace.id
    session.add(
        WorkspaceAutonomyPolicy(
            tenant_id=tenant.id, workspace_id=workspace.id, level=AutonomyLevel.OBSERVE_ONLY
        )
    )
    await session.commit()
    session.add(
        WorkspaceAutonomyPolicy(
            tenant_id=tenant.id, workspace_id=workspace.id, level=AutonomyLevel.RECOMMEND_ONLY
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    other = Tenant(name="Other")
    session.add(other)
    await session.commit()
    session.add(
        WorkspaceAutonomyPolicy(
            tenant_id=other.id, workspace_id=workspace_id, level=AutonomyLevel.OBSERVE_ONLY
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_postgresql_enforces_enum_null_and_database_default(
    postgres_session: AsyncSession,
) -> None:
    tenant, workspace = await create_workspace(postgres_session)
    await postgres_session.execute(
        text(
            "INSERT INTO workspace_autonomy_policies "
            "(id, tenant_id, workspace_id, level) "
            "VALUES (:id, :tenant, :workspace, 'observe_only')"
        ),
        {"id": uuid4(), "tenant": tenant.id, "workspace": workspace.id},
    )
    assert (
        await postgres_session.scalar(text("SELECT is_paused FROM workspace_autonomy_policies"))
        is True
    )
    await postgres_session.commit()
    await postgres_session.execute(delete(WorkspaceAutonomyPolicy))
    await postgres_session.commit()
    for statement in (
        "INSERT INTO workspace_autonomy_policies (id, tenant_id, workspace_id, level) "
        "VALUES (:id, :tenant, :workspace, 'invalid')",
        "INSERT INTO workspace_autonomy_policies "
        "(id, tenant_id, workspace_id, level, is_paused) "
        "VALUES (:id, :tenant, :workspace, 'observe_only', NULL)",
    ):
        with pytest.raises(IntegrityError):
            await postgres_session.execute(
                text(statement), {"id": uuid4(), "tenant": tenant.id, "workspace": workspace.id}
            )
            await postgres_session.commit()
        await postgres_session.rollback()


async def test_postgresql_rejects_duplicate_and_cross_tenant_policy(
    postgres_session: AsyncSession,
) -> None:
    await test_database_rejects_duplicate_and_cross_tenant_policy(postgres_session)
