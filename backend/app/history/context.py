from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.history.models import (
    MAX_RECAP_PROMPT_CHARACTERS,
    MAX_RECAP_RESULT_CHARACTERS,
    PersistedTaskData,
    TaskRecap,
)
from app.history.repository import HistoryRepository
from app.models.task import TaskStatus


@dataclass(frozen=True)
class SessionContext:
    rounds: list[list[dict[str, Any]]]
    candidate_tasks: int
    skipped_tasks: int


def build_task_recap(value: PersistedTaskData) -> TaskRecap | None:
    task = value.task
    if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED} or task.summary is None:
        return None
    prompt = task.prompt[:MAX_RECAP_PROMPT_CHARACTERS]
    if task.status is TaskStatus.COMPLETED:
        return TaskRecap(
            task_id=task.id,
            ordinal=value.ordinal,
            status="COMPLETED",
            user_prompt=prompt,
            assistant_result=(task.result or "")[:MAX_RECAP_RESULT_CHARACTERS],
            files_changed=list(task.summary.files_changed),
            verification=task.summary.verification,
        )
    if task.error is None:
        return None
    return TaskRecap(
        task_id=task.id,
        ordinal=value.ordinal,
        status="FAILED",
        user_prompt=prompt,
        error_code=task.error.code,
        files_changed=list(task.summary.files_changed),
        verification=task.summary.verification,
    )


class SessionContextBuilder:
    def __init__(self, repository: HistoryRepository) -> None:
        self.repository = repository

    def build(self, session_id: str) -> SessionContext:
        tasks, _ = self.repository.list_session_tasks(session_id, 100)
        recaps: list[TaskRecap] = []
        skipped = 0
        for persisted in reversed(tasks):
            recap = build_task_recap(persisted)
            if recap is None:
                skipped += 1
            else:
                recaps.append(recap)
        rounds = [
            [
                {
                    "role": "user",
                    "content": (
                        f"Historical task {recap.ordinal} user request:\n{recap.user_prompt}"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Historical task recap (deterministic runtime facts):\n"
                    + json.dumps(recap.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                },
            ]
            for recap in recaps
        ]
        return SessionContext(rounds=rounds, candidate_tasks=len(recaps), skipped_tasks=skipped)
