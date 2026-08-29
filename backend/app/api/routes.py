from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.models.task import Task, TaskCreate
from app.services.tasks import TaskBusy, TaskCapacity, TaskManager, TaskPersistenceUnavailable

router = APIRouter(prefix="/api")


def manager(request: Request) -> TaskManager:
    return request.app.state.tasks


@router.get("/meta")
async def metadata(request: Request) -> dict:
    # Whitelist public configuration; never serialize Settings.
    return {
        "workspace": request.app.state.workspace.root.name,
        "mode": request.app.state.mode,
        "agent_ready": request.app.state.agent_ready,
        "tools": [s["function"]["name"] for s in request.app.state.tools.schemas()],
        "tool_statuses": request.app.state.tools.availability(),
    }


@router.post("/tasks", status_code=202, response_model=Task)
async def create_task(body: TaskCreate, request: Request) -> Task:
    try:
        return await manager(request).create(body.prompt)
    except TaskBusy as exc:
        raise HTTPException(409, "A task is already running") from exc
    except TaskCapacity as exc:
        raise HTTPException(503, "History capacity has been reached") from exc
    except TaskPersistenceUnavailable as exc:
        raise HTTPException(503, "Task history is temporarily unavailable") from exc


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, request: Request) -> Task:
    try:
        return manager(request).get(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Task not found") from exc


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, after: int = 0) -> Response:
    await get_task(task_id, request)
    log = manager(request).get_log(task_id)
    try:
        cursor = int(request.headers.get("last-event-id", str(after)))
    except ValueError as exc:
        raise HTTPException(400, "Invalid event cursor") from exc
    if cursor < 0 or cursor > log.last_id:
        raise HTTPException(400, "Event cursor out of range")
    if not log.cursor_available(cursor):
        raise HTTPException(410, "Event history for this cursor has expired")
    if log.closed and cursor == log.last_id:
        # EventSource treats HTTP 204 as 'do not reconnect'.
        return Response(status_code=204)
    return StreamingResponse(
        log.stream(after=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
