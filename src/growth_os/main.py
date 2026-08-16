from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from growth_os.api.health import ReadinessProbe, create_health_router
from growth_os.core.config import Settings, get_settings
from growth_os.db.session import (
    check_database,
    create_database_engine,
    create_session_factory,
)


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app_readiness_probe: ReadinessProbe

    if readiness_probe is None:
        engine = create_database_engine(app_settings.database_url.get_secret_value())
        session_factory = create_session_factory(engine)

        async def database_readiness_probe() -> None:
            await check_database(session_factory)

        app_readiness_probe = database_readiness_probe
    else:
        engine = None
        app_readiness_probe = readiness_probe

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.include_router(create_health_router(app_readiness_probe))
    return app


app = create_app()
