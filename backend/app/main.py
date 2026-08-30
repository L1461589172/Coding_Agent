from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.agent.runtime import TaskRunner
from app.api.routes import router
from app.core.config import Settings
from app.services.workspaces import WorkspaceService
from app.tools.workspace import Workspace


def create_app(settings: Settings | None = None, runner: TaskRunner | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    workspace = Workspace(config.workspace)
    workspace_service = WorkspaceService(config, workspace, runner)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await workspace_service.open()
            workspace_service.publish(app.state)
            yield
        finally:
            await workspace_service.close()

    app = FastAPI(title="Coding Agent", version=__version__, lifespan=lifespan)
    app.state.workspace_service = workspace_service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def local_origins_only(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in config.allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "mode": app.state.mode,
            "agent_ready": app.state.agent_ready,
        }

    @app.get("/")
    async def root() -> dict:
        return {
            "message": "Backend is running. Start the Vue dev server separately.",
            "frontend": "http://localhost:5173",
            "api_docs": "/docs",
        }

    app.include_router(router)
    return app
