from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.agent.context import ContextBudget
from app.agent.llm import OpenAICompatibleLLMClient
from app.agent.runtime import AgentRuntime, TaskRunner
from app.api.routes import router
from app.core.config import APPLICATION_ROOT, Settings
from app.core.events import EventLimits
from app.history.repository import JsonHistoryRepository
from app.services.tasks import TaskManager
from app.tools.registry import create_registry
from app.tools.workspace import Workspace


def create_app(settings: Settings | None = None, runner: TaskRunner | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    workspace = Workspace(config.workspace)
    tools = create_registry(workspace)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        llm = (
            OpenAICompatibleLLMClient.from_settings(config)
            if runner is None and config.model_configured
            else None
        )
        runtime = runner or AgentRuntime(
            workspace,
            tools,
            llm,
            max_steps=config.max_steps,
            context_budget=ContextBudget(
                max_characters=config.context_max_characters,
                max_tokens=config.context_max_tokens,
                max_tool_result_characters=config.tool_result_max_characters,
            ),
            recent_rounds=config.context_recent_rounds,
            max_consecutive_llm_errors=config.max_consecutive_llm_errors,
            max_consecutive_runtime_errors=config.max_consecutive_runtime_errors,
            max_consecutive_command_timeouts=config.max_consecutive_command_timeouts,
        )
        ready = runner is not None or runtime.ready
        app.state.workspace = workspace
        app.state.tools = tools
        app.state.agent_ready = ready
        app.state.mode = "agent" if ready else "scaffold"
        event_limits = EventLimits(
            max_payload_characters=config.event_max_payload_characters,
            max_history_characters=config.event_max_history_characters,
            max_history_events=config.event_max_history_events,
        )
        history = JsonHistoryRepository(
            config.resolved_history_dir,
            workspace.root,
            event_limits,
            application_root=APPLICATION_ROOT if config.history_dir is None else None,
            max_sessions=config.history_max_sessions,
            max_tasks_per_session=config.history_max_tasks_per_session,
            backup_limit=config.history_backup_limit,
            backup_max_bytes=config.history_backup_max_bytes,
            max_bytes=config.history_max_bytes,
        )
        tasks: TaskManager | None = None
        try:
            await history.open()
            await history.reconcile_interrupted()
            tasks = TaskManager(
                runtime,
                config.max_tasks,
                app.state.mode,
                event_limits,
                repository=history,
            )
            app.state.tasks = tasks
            yield
        finally:
            try:
                if tasks is not None:
                    await tasks.close()
                else:
                    await history.close()
            finally:
                if runner is None:
                    await runtime.close()

    app = FastAPI(title="Coding Agent", version=__version__, lifespan=lifespan)
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
