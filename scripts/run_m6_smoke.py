"""Run one bounded real-model M6 multi-turn/restart smoke without exposing credentials."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Any

from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "output" / "m6-real-smoke-workspace"
WORKSPACE = RUN_ROOT / "workspace"
HISTORY = RUN_ROOT / "history"
REPORT = ROOT / "output" / "m6-real-smoke.json"
SOURCE = WORKSPACE / "calculator.py"
TEST_FILE = WORKSPACE / "test_calculator.py"

BASELINE_SOURCE = '''"""Small calculator module used by the Coding Agent M6 smoke."""


def divide(dividend: float, divisor: float) -> float | None:
    """Return the quotient, or None when the divisor is zero."""
    return dividend / divisor
'''
BASELINE_TEST = """from calculator import divide


def test_divide_regular_numbers():
    assert divide(10, 2) == 5
    assert divide(7, 2) == 3.5


def test_divide_by_zero_returns_none():
    assert divide(10, 0) is None
"""

PROMPTS = (
    "修复 calculator.py 的 divide：除数为 0 时返回 None，其他行为不变。"
    "先读取源码和测试，只做必要修改并运行 pytest；不要修改测试。",
    "继续刚才的工作。不要修改文件；请重新读取当前 calculator.py 和测试，"
    "运行 pytest，并确认刚才的修复仍然有效。",
    "服务已经重启。请继续这个会话，不要修改文件；再次读取当前实现，"
    "只说明 divide 的除零行为，并运行 pytest 确认。",
)


def decode_sse(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def execute(
    client: TestClient, url: str, prompt: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    created = client.post(url, json={"prompt": prompt})
    created.raise_for_status()
    task_id = created.json()["id"]
    stream = client.get(f"/api/tasks/{task_id}/events")
    stream.raise_for_status()
    task = client.get(f"/api/tasks/{task_id}").json()
    return task, decode_sse(stream.text)


def round_metrics(task: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    tools = [event["payload"].get("tool") for event in events if event["type"] == "tool_started"]
    return {
        "ordinal": task["ordinal"],
        "status": task["status"],
        "error_code": (task.get("error") or {}).get("code"),
        "tool_calls": len(tools),
        "tool_names": tools,
        "read_current_files": any(
            name in {"read_file", "search_text", "list_files"} for name in tools
        ),
        "ran_tests": "run_command" in tools,
        "changed_files": (task.get("summary") or {}).get("files_changed", []),
    }


def main() -> int:
    if RUN_ROOT.exists():
        shutil.rmtree(RUN_ROOT)
    WORKSPACE.mkdir(parents=True)
    SOURCE.write_text(BASELINE_SOURCE, encoding="utf-8", newline="\n")
    TEST_FILE.write_text(BASELINE_TEST, encoding="utf-8", newline="\n")
    settings = replace(Settings.from_env(workspace=str(WORKSPACE)), history_dir=HISTORY)
    if not settings.model_configured:
        raise RuntimeError("Model configuration is incomplete")

    started = monotonic()
    rounds: list[dict[str, Any]] = []
    session_id = ""
    try:
        with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
            first, first_events = execute(client, "/api/tasks", PROMPTS[0])
            session_id = first["session_id"]
            second, second_events = execute(client, f"/api/sessions/{session_id}/tasks", PROMPTS[1])
            rounds.extend(
                [round_metrics(first, first_events), round_metrics(second, second_events)]
            )

        with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
            restored = client.get(f"/api/sessions/{session_id}/tasks?limit=20")
            restored.raise_for_status()
            third, third_events = execute(client, f"/api/sessions/{session_id}/tasks", PROMPTS[2])
            rounds.append(round_metrics(third, third_events))
            restored_ordinals = [item["ordinal"] for item in restored.json()["items"]]

        persisted = "\n".join(
            path.read_text("utf-8", errors="ignore")
            for path in HISTORY.rglob("*.json")
            if path.is_file()
        )
        checks = {
            "three_terminal_rounds": [item["status"] for item in rounds]
            == ["COMPLETED", "COMPLETED", "COMPLETED"],
            "single_session_monotonic_ordinals": [item["ordinal"] for item in rounds] == [1, 2, 3],
            "restart_restored_first_two_rounds": restored_ordinals == [2, 1],
            "first_round_changed_implementation": rounds[0]["changed_files"] == ["calculator.py"],
            "follow_ups_read_current_files": all(item["read_current_files"] for item in rounds[1:]),
            "all_rounds_ran_tests": all(item["ran_tests"] for item in rounds),
            "model_key_not_persisted": settings.api_key not in persisted,
            "test_file_unchanged": TEST_FILE.read_text(encoding="utf-8") == BASELINE_TEST,
        }
        report = {
            "success": all(checks.values()),
            "elapsed_seconds": round(monotonic() - started, 3),
            "session_id": session_id,
            "rounds": rounds,
            "checks": checks,
        }
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["success"] else 1
    finally:
        shutil.rmtree(RUN_ROOT, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
