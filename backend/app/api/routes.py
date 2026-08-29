from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.history.errors import (
    HistoryDataInvalid,
    HistoryStorageUnavailable,
    SessionActive,
    SessionNotFound,
)
from app.history.models import SessionData, SessionListItem, SessionPage, TaskPage
from app.models.task import Task, TaskCreate
from app.services.tasks import (
    TaskBusy,
    TaskCapacity,
    TaskManager,
    TaskPersistenceUnavailable,
    TaskSessionLimit,
)

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


def _session_item(value: SessionData) -> SessionListItem:
    return SessionListItem(
        id=value.id,
        title=value.title,
        created_at=value.created_at,
        updated_at=value.updated_at,
        task_count=value.task_count,
        last_task_id=value.last_task_id,
        last_task_status=value.last_task_status,
        history_incomplete=value.history_incomplete,
    )


@router.get("/sessions", response_model=SessionPage)
async def list_sessions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    before: str | None = Query(default=None, min_length=1, max_length=256),
) -> SessionPage:
    try:
        items, cursor = manager(request).list_sessions(limit, before)
        return SessionPage(items=[_session_item(item) for item in items], next_cursor=cursor)
    except HistoryDataInvalid as exc:
        raise HTTPException(400, "Invalid Session cursor") from exc


@router.get("/sessions/{session_id}", response_model=SessionListItem)
async def get_session(session_id: str, request: Request) -> SessionListItem:
    try:
        return _session_item(manager(request).get_session(session_id))
    except (SessionNotFound, HistoryStorageUnavailable) as exc:
        raise HTTPException(404, "Session not found") from exc


@router.get("/sessions/{session_id}/tasks", response_model=TaskPage)
async def list_session_tasks(
    session_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    before_ordinal: int | None = Query(default=None, ge=1, le=101),
) -> TaskPage:
    try:
        items, cursor = manager(request).list_session_tasks(session_id, limit, before_ordinal)
        return TaskPage(
            items=[item.task for item in items],
            next_before_ordinal=cursor,
        )
    except (SessionNotFound, HistoryStorageUnavailable) as exc:
        raise HTTPException(404, "Session not found") from exc


@router.post("/sessions/{session_id}/tasks", status_code=202, response_model=Task)
async def create_follow_up(session_id: str, body: TaskCreate, request: Request) -> Task:
    try:
        return await manager(request).create(body.prompt, session_id)
    except TaskBusy as exc:
        raise HTTPException(409, "A task is already running") from exc
    except SessionNotFound as exc:
        raise HTTPException(404, "Session not found") from exc
    except TaskSessionLimit as exc:
        raise HTTPException(409, "Session task limit has been reached") from exc
    except (TaskCapacity, TaskPersistenceUnavailable) as exc:
        raise HTTPException(503, "Task history is temporarily unavailable") from exc


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    try:
        await manager(request).delete_session(session_id)
    except SessionActive as exc:
        raise HTTPException(409, "Active Session cannot be deleted") from exc
    except (SessionNotFound, HistoryStorageUnavailable) as exc:
        raise HTTPException(404, "Session not found") from exc
    return Response(status_code=204)


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
        raise HTTPException(
            410,
            {
                "code": "EVENT_HISTORY_EXPIRED",
                "earliest_event_id": log.first_id,
                "latest_event_id": log.last_id,
            },
        )
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
