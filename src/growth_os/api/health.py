from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

ReadinessProbe = Callable[[], Awaitable[None]]


def create_health_router(readiness_probe: ReadinessProbe) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready")
    async def readiness() -> JSONResponse:
        try:
            await readiness_probe()
        except Exception:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "checks": {"database": "unavailable"},
                },
            )

        return JSONResponse(content={"status": "ready", "checks": {"database": "ok"}})

    return router
