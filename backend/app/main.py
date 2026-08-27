from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.agent.runtime import AgentRuntime, TaskRunner
from app.api.routes import router
from app.core.config import Settings
from app.services.tasks import TaskManager
from app.tools.registry import create_registry
from app.tools.workspace import Workspace


def create_app(settings: Settings | None = None, runner: TaskRunner | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    workspace = Workspace(config.workspace)
    tools = create_registry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.workspace = workspace
        app.state.tools = tools
        app.state.tasks = TaskManager(runner or AgentRuntime(workspace, tools), config.max_tasks)
        try:
            yield
        finally:
            await app.state.tasks.close()

    app = FastAPI(title="Coding Agent", version=__version__, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["GET", "POST"],
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
        return {"status": "ok", "version": __version__, "mode": "scaffold", "agent_ready": False}

    @app.get("/")
    async def root() -> dict:
        return {
            "message": "Backend is running. Start the Vue dev server separately.",
            "frontend": "http://localhost:5173",
            "api_docs": "/docs",
        }

    app.include_router(router)
    return app
