from collections.abc import Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient

from growth_os.main import create_app

ReadinessProbe = Callable[[], Awaitable[None]]


async def ready_database() -> None:
    return None


async def unavailable_database() -> None:
    raise ConnectionError("database is unavailable")


@pytest.mark.parametrize("probe", [ready_database, unavailable_database])
async def test_health_is_live_without_checking_dependencies(probe: ReadinessProbe) -> None:
    transport = ASGITransport(app=create_app(readiness_probe=probe))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_succeeds_when_database_is_reachable() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=ready_database))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_readiness_fails_when_database_is_unreachable() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=unavailable_database))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }
