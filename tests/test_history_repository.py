import asyncio
import json
import multiprocessing
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.events import EventLimits
from app.history import atomic as history_atomic
from app.history import migrations as history_migrations
from app.history.atomic import atomic_write_json
from app.history.errors import (
    HistoryDataInvalid,
    HistoryFormatUnsupported,
    HistoryLockUnavailable,
    HistoryStorageUnavailable,
)
from app.history.lock import HistoryFileLock
from app.history.models import SessionEnvelope, TaskRecap
from app.history.repository import InMemoryHistoryRepository, JsonHistoryRepository
from app.models.task import Task, TaskStatus
from app.services.tasks import TaskManager
from app.services.trace import ExecutionTrace
from pydantic import ValidationError


class ImmediateRunner:
    async def run(self, task, events):
        await events.publish(task.id, "assistant_message", {"message": "done"})
        return "done"


def _hold_history_lock(path, ready, release):
    lock = HistoryFileLock(path)
    lock.acquire()
    try:
        ready.set()
        release.wait(10)
    finally:
        lock.release()


def repository(history_dir, workspace, *, limits=None):
    return JsonHistoryRepository(history_dir, workspace, limits)


def test_phase_zero_recap_contract_is_strict_and_bounded():
    task_id = str(uuid4())
    completed = TaskRecap(
        task_id=task_id,
        ordinal=1,
        status="COMPLETED",
        user_prompt="fix it",
        assistant_result="fixed",
        files_changed=["app.py"],
    )
    assert completed.task_id == task_id

    with pytest.raises(ValidationError):
        TaskRecap(
            task_id=task_id,
            ordinal=1,
            status="FAILED",
            user_prompt="fix it",
            assistant_result="unverified conclusion",
            error_code="SERVER_RESTARTED",
        )
    with pytest.raises(ValidationError):
        TaskRecap(
            task_id=task_id,
            ordinal=1,
            status="COMPLETED",
            user_prompt="x" * 4_001,
            assistant_result="fixed",
        )


def test_repository_session_cursor_is_opaque_strict_and_stable_for_ties():
    async def scenario():
        store = InMemoryHistoryRepository()
        task_ids = []
        for prompt in ("one", "two", "three"):
            task = Task(prompt=prompt)
            task_ids.append(task.id)
            await store.create_with_task(task, ExecutionTrace())
        tied = datetime(2026, 8, 29, tzinfo=UTC)
        for session in store.sessions.values():
            session.data.updated_at = tied

        expected_ids = sorted(store.sessions, reverse=True)
        first, cursor = store.list_sessions(2)
        assert [session.id for session in first] == expected_ids[:2]
        assert cursor is not None and all(character.isascii() for character in cursor)
        second, next_cursor = store.list_sessions(2, cursor)
        assert [session.id for session in second] == expected_ids[2:]
        assert next_cursor is None
        with pytest.raises(HistoryDataInvalid):
            store.list_sessions(2, cursor + "=")

        session_id = store.task_sessions[task_ids[0]]
        tasks, before_ordinal = store.list_session_tasks(session_id, 20)
        assert [task.task.id for task in tasks] == [task_ids[0]]
        assert before_ordinal is None

    asyncio.run(scenario())


def test_empty_repository_initializes_v1_and_reopens_idempotently(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        paths = first.paths
        assert paths is not None
        workspace_file = paths.workspace() / "workspace.json"
        index_file = paths.workspace() / "index.json"
        format_before = (paths.version() / "format.json").read_bytes()
        index_before = index_file.read_bytes()
        assert paths.current.read_text(encoding="utf-8") == "v1\n"
        assert format_before.endswith(b"\n")
        assert workspace_file.is_file()
        assert (paths.workspace() / "sessions").is_dir()
        assert (paths.workspace() / "trash").is_dir()
        await first.close()

        second = repository(history_dir, tmp_path)
        await second.open()
        assert (paths.version() / "format.json").read_bytes() == format_before
        assert index_file.read_bytes() == index_before
        await second.close()

    asyncio.run(scenario())


def test_history_lock_is_exclusive_and_released(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        second = repository(history_dir, tmp_path)
        await first.open()
        with pytest.raises(HistoryLockUnavailable):
            await second.open()
        await first.close()
        await second.open()
        await second.close()

    asyncio.run(scenario())


def test_history_lock_is_exclusive_across_spawned_processes(history_dir):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    lock_path = history_dir / "cross-process.lock"
    process = context.Process(target=_hold_history_lock, args=(lock_path, ready, release))
    process.start()
    contender = HistoryFileLock(lock_path)
    try:
        assert ready.wait(5), f"lock holder did not start; exit={process.exitcode}"
        with pytest.raises(HistoryLockUnavailable):
            contender.acquire()
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
    assert process.exitcode == 0
    contender.acquire()
    contender.release()


def test_history_root_link_is_rejected(history_dir, tmp_path):
    real = history_dir / "real"
    real.mkdir()
    linked = history_dir / "linked"
    try:
        os.symlink(real, linked, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit creating symlinks for this test user")

    async def scenario():
        linked_repository = repository(linked, tmp_path)
        with pytest.raises(HistoryStorageUnavailable):
            await linked_repository.open()

    asyncio.run(scenario())


def test_future_format_is_rejected_without_modification(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        current = first.paths.current
        await first.close()
        current.write_text("v2\n", encoding="utf-8")

        incompatible = repository(history_dir, tmp_path)
        with pytest.raises(HistoryFormatUnsupported):
            await incompatible.open()
        assert current.read_text(encoding="utf-8") == "v2\n"

        current.write_text("v1\n", encoding="utf-8")
        recovered = repository(history_dir, tmp_path)
        await recovered.open()
        await recovered.close()

    asyncio.run(scenario())


def test_synthetic_v0_migrates_with_backup(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        paths = first.paths
        await first.close()

        v1 = paths.version(1)
        for json_path in v1.rglob("*.json"):
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            raw["format_version"] = 0
            json_path.write_text(json.dumps(raw), encoding="utf-8")
        os.replace(v1, paths.version(0))
        paths.current.write_text("v0\n", encoding="utf-8")

        migrated = repository(history_dir, tmp_path)
        await migrated.open()
        assert paths.current.read_text(encoding="utf-8") == "v1\n"
        assert json.loads((paths.version(1) / "format.json").read_text())["format_version"] == 1
        backups = [path for path in paths.backups.iterdir() if path.is_dir()]
        assert len(backups) == 1
        assert (backups[0] / "format.json").is_file()
        await migrated.close()

    asyncio.run(scenario())


def test_failed_v0_migration_keeps_current_and_removes_staging(history_dir, tmp_path, monkeypatch):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        paths = first.paths
        await first.close()

        v1 = paths.version(1)
        for json_path in v1.rglob("*.json"):
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            raw["format_version"] = 0
            json_path.write_text(json.dumps(raw), encoding="utf-8")
        os.replace(v1, paths.version(0))
        paths.current.write_text("v0\n", encoding="utf-8")

        def reject_migration(_root):
            raise HistoryDataInvalid("injected migration validation failure")

        monkeypatch.setattr(history_migrations, "_validate_tree", reject_migration)
        failed = repository(history_dir, tmp_path)
        with pytest.raises(HistoryDataInvalid):
            await failed.open()
        assert paths.current.read_text(encoding="utf-8") == "v0\n"
        assert not paths.version(1).exists()
        assert list(paths.root.glob(".history-version-tmp-*")) == []

    asyncio.run(scenario())


def test_projection_corruption_is_quarantined_and_rebuilt(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        manager = TaskManager(ImmediateRunner(), mode="agent", repository=first)
        task = await manager.create("persist this task")
        await manager._job
        paths = first.paths
        persisted = first.get_persisted_task(task.id)
        session_dir = paths.session(persisted.session_id)
        await manager.close()

        (paths.workspace() / "index.json").write_text("{broken", encoding="utf-8")
        (session_dir / "session.json").write_text("{broken", encoding="utf-8")
        staging = paths.sessions() / f".session-tmp-{uuid4()}"
        staging.mkdir()
        (staging / "orphan").write_text("temporary", encoding="utf-8")

        reopened = repository(history_dir, tmp_path)
        await reopened.open()
        assert reopened.get_task(task.id).status is TaskStatus.COMPLETED
        assert not staging.exists()
        SessionEnvelope.model_validate_json((session_dir / "session.json").read_text())
        quarantine = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in paths.quarantine.glob("*.json")
        )
        assert "HISTORY_INDEX_INVALID" in quarantine
        assert "HISTORY_SESSION_INVALID" in quarantine
        await reopened.close()

    asyncio.run(scenario())


def test_one_invalid_task_is_isolated_without_hiding_valid_task(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        manager = TaskManager(ImmediateRunner(), mode="agent", repository=first)
        task = await manager.create("keep valid task")
        await manager._job
        persisted = first.get_persisted_task(task.id)
        paths = first.paths
        tasks_dir = paths.session(persisted.session_id) / "tasks"
        await manager.close()

        invalid = tasks_dir / f"{2:010d}-{uuid4()}.json"
        invalid.write_text("{broken", encoding="utf-8")
        reopened = repository(history_dir, tmp_path)
        await reopened.open()
        assert reopened.get_task(task.id).status is TaskStatus.COMPLETED
        assert reopened.sessions[persisted.session_id].data.history_incomplete is True
        assert not invalid.exists()
        assert any(
            "HISTORY_TASK_INVALID" in path.read_text() for path in paths.quarantine.glob("*.json")
        )
        await reopened.close()

    asyncio.run(scenario())


def test_many_invalid_tasks_stop_startup_instead_of_claiming_empty_history(history_dir, tmp_path):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        task = Task(prompt="retain valid history")
        await first.create_with_task(task, ExecutionTrace())
        persisted = first.get_persisted_task(task.id)
        paths = first.paths
        tasks_dir = paths.session(persisted.session_id) / "tasks"
        await first.close()

        for ordinal in range(2, 13):
            (tasks_dir / f"{ordinal:010d}-{uuid4()}.json").write_text("{broken", encoding="utf-8")
        failed = repository(history_dir, tmp_path)
        with pytest.raises(HistoryDataInvalid):
            await failed.open()

        # The failed open released history.lock; valid history is not replaced
        # with an empty workspace projection.
        assert (tasks_dir / f"{1:010d}-{task.id}.json").is_file()
        recovered = repository(history_dir, tmp_path)
        await recovered.open()
        assert recovered.get_task(task.id).prompt == "retain valid history"
        await recovered.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("initial", [TaskStatus.PENDING, TaskStatus.RUNNING])
def test_interrupted_task_reconciles_exactly_once(history_dir, tmp_path, initial):
    async def scenario():
        first = repository(history_dir, tmp_path)
        await first.open()
        task = Task(prompt="interrupted")
        if initial is TaskStatus.RUNNING:
            task.status = TaskStatus.RUNNING
            task.started_at = task.created_at
        await first.create_with_task(task, ExecutionTrace())
        await first.close()

        second = repository(history_dir, tmp_path)
        await second.open()
        assert await second.reconcile_interrupted() == [task.id]
        persisted = second.get_persisted_task(task.id)
        assert persisted.task.status is TaskStatus.FAILED
        assert persisted.task.error.code == "SERVER_RESTARTED"
        assert [event.type for event in persisted.events] == ["task_failed"]
        revision = second.tasks[task.id].revision
        await second.close()

        third = repository(history_dir, tmp_path)
        await third.open()
        assert await third.reconcile_interrupted() == []
        assert third.tasks[task.id].revision == revision
        await third.close()

    asyncio.run(scenario())


def test_terminal_task_is_readable_after_memory_eviction_and_restart(history_dir, tmp_path):
    async def scenario():
        limits = EventLimits(
            max_payload_characters=256,
            max_history_events=3,
            max_history_characters=4_000,
        )
        first = repository(history_dir, tmp_path, limits=limits)
        await first.open()
        manager = TaskManager(
            ImmediateRunner(), mode="agent", event_limits=limits, repository=first
        )
        task = await manager.create("complete durably")
        await manager._job
        assert task.id not in manager.tasks
        assert task.id not in manager.traces
        assert task.id not in manager.logs
        assert manager.get(task.id).status is TaskStatus.COMPLETED
        assert manager.get_log(task.id).closed is True
        await manager.close()

        second = repository(history_dir, tmp_path, limits=limits)
        await second.open()
        restored = TaskManager(
            ImmediateRunner(), mode="agent", event_limits=limits, repository=second
        )
        assert restored.get(task.id).result == "done"
        assert restored.get_log(task.id).closed is True
        await restored.close()

    asyncio.run(scenario())


def test_failed_event_commit_is_not_published_before_terminal_recovery():
    class FailFirstCommit(InMemoryHistoryRepository):
        def __init__(self):
            super().__init__()
            self.commits = 0

        async def commit_task_event(self, task, event, trace):
            self.commits += 1
            if self.commits == 1:
                raise HistoryStorageUnavailable("injected failure")
            await super().commit_task_event(task, event, trace)

    async def scenario():
        store = FailFirstCommit()
        manager = TaskManager(ImmediateRunner(), mode="agent", repository=store)
        task = await manager.create("fail first event")
        await manager._job
        persisted = store.get_persisted_task(task.id)
        assert persisted.task.status is TaskStatus.FAILED
        assert [event.type for event in persisted.events] == ["task_failed"]
        assert [event.type for event in manager.get_log(task.id)._events] == ["task_failed"]
        await manager.close()

    asyncio.run(scenario())


def test_atomic_replace_failure_preserves_old_json(history_dir, monkeypatch):
    target = history_dir / "atomic.json"
    atomic_write_json(target, {"revision": 1})
    original = target.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(history_atomic.os, "replace", fail_replace)
    with pytest.raises(HistoryStorageUnavailable):
        atomic_write_json(target, {"revision": 2})
    assert target.read_bytes() == original
    assert list(history_dir.glob(".history-tmp-*")) == []


def test_atomic_replace_unknown_result_uses_committed_target(history_dir, monkeypatch):
    target = history_dir / "atomic.json"
    atomic_write_json(target, {"revision": 1})
    real_replace = history_atomic.os.replace

    def commit_then_report_failure(source, destination):
        real_replace(source, destination)
        raise OSError("injected post-commit failure")

    monkeypatch.setattr(history_atomic.os, "replace", commit_then_report_failure)
    atomic_write_json(target, {"revision": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"revision": 2}
    assert list(history_dir.glob(".history-tmp-*")) == []


def test_same_workspace_basename_does_not_share_history(history_dir, tmp_path):
    async def scenario():
        first_workspace = tmp_path / "one" / "project"
        second_workspace = tmp_path / "two" / "project"
        first_workspace.mkdir(parents=True)
        second_workspace.mkdir(parents=True)

        first = repository(history_dir, first_workspace)
        await first.open()
        task = Task(prompt="workspace one")
        await first.create_with_task(task, ExecutionTrace())
        first_fingerprint = first.paths.fingerprint
        await first.close()

        second = repository(history_dir, second_workspace)
        await second.open()
        assert second.paths.fingerprint != first_fingerprint
        with pytest.raises(KeyError):
            second.get_task(task.id)
        await second.close()

    asyncio.run(scenario())
