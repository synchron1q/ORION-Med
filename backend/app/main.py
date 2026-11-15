# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""ORION-MED // HEV-1 - FastAPI application entry point.

Run:  uvicorn app.main:app --port 8000      (from the backend/ folder)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import get_core, get_db
from app.api.routes import router
from app.cfms.routes import router as fitness_router
from app.core.settings import APP_VERSION, Settings
from app.integrations.nasa_donki import get_nasa_donki_context
from app.schemas.state import HevSystemState
from app.services.core import HevCore

log = logging.getLogger("orion")


async def _loop(name: str, interval_s: float, fn, initial_delay_s: float = 0.0) -> None:
    """Run a blocking job periodically in a worker thread. Errors never stop the loop."""
    await asyncio.sleep(initial_delay_s)
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception:  # pragma: no cover - logged, loop continues
            log.exception("Background job %s failed", name)
        await asyncio.sleep(interval_s)


def create_app(settings: Settings | None = None, core: HevCore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.core = core or HevCore(settings)
        tasks: list[asyncio.Task] = []
        if settings.background_tasks:
            c: HevCore = app.state.core
            tick = float(c.reg.simulator.get("tick_interval_s", 1.0))
            tasks.append(asyncio.create_task(_loop("tick", tick, c.tick)))
            tasks.append(asyncio.create_task(_loop("sync", float(c.reg.sync.get("interval_s", 3)), c.sync.run_once, 2)))
            if settings.external_fetch_enabled:
                tasks.append(asyncio.create_task(_loop("osdr", float(c.reg.osdr.get("refresh_interval_s", 86400)), c.osdr.refresh, 15)))
        log.info("ORION-MED // HEV-1 v%s ready (demo_mode=%s)", APP_VERSION, settings.demo_mode)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            app.state.core.engine.dispose()

    app = FastAPI(
        title="ORION-MED // HEV-1 API",
        version=APP_VERSION,
        description="Autonomous astronaut health monitoring and decision-support prototype. "
        "NOT a certified medical device. All thresholds are demonstration values.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    app.include_router(fitness_router)

    @app.get("/api/state", tags=["state"], response_model=None,
             summary="Complete HEV-1 system state for the crew interface (polled at 1 Hz).")
    async def get_state(request: Request, since: int | None = None, db: Session = Depends(get_db),
                        core: HevCore = Depends(get_core)) -> HevSystemState:
        state: dict[str, Any] = await run_in_threadpool(core.dashboard, since)
        state["nasa_donki"] = await get_nasa_donki_context(db, allow_fetch=settings.external_fetch_enabled)
        state["space_weather_simulation"] = core.simulator.simulated_space_weather()
        state["readiness"] = core.readiness(state, state["nasa_donki"])
        state["fitness"] = await run_in_threadpool(core.fitness.summary, state) if core.fitness else {"enabled": False}
        return state  # type: ignore[return-value]

    dist = settings.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        class SPAStaticFiles(StaticFiles):
            async def get_response(self, path: str, scope):  # type: ignore[override]
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if exc.status_code == 404 and not path.startswith("api"):
                        return FileResponse(dist / "index.html")
                    raise

        app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def root() -> dict[str, str]:
            return {"service": "ORION-MED // HEV-1", "version": APP_VERSION,
                    "ui": "Frontend build not found. Run 'npm run build' in frontend/ or 'npm run dev' for development.",
                    "docs": "/docs"}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
