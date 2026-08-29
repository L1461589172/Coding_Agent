"""Run the real-model M4 demo repeatedly without exposing model credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from time import monotonic
from typing import Any

from app.core.config import Settings
from app.main import create_app
from app.tools.command_policy import child_environment
from app.tools.workspace import Workspace
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_workspace"
SOURCE = DEMO / "calculator.py"
TEST_FILE = DEMO / "test_calculator.py"
BASELINE_SOURCE = '''"""Small calculator module used by the Coding Agent demo."""


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
PROMPT = (
    "修复 calculator.py 中的 divide：除数为 0 时返回 None，普通除法行为保持不变。"
    "不要修改测试。先检查工作区和相关源码/测试，只做必要修改，然后运行完整 pytest；"
    "只有测试真实通过后才能结束。"
)


def reset_demo() -> None:
    SOURCE.write_text(BASELINE_SOURCE, encoding="utf-8", newline="\n")
    TEST_FILE.write_text(BASELINE_TEST, encoding="utf-8", newline="\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest() -> subprocess.CompletedProcess[str]:
    workspace = Workspace(DEMO)
    environment = child_environment(workspace)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=DEMO,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def decode_sse(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def run_once(number: int) -> dict[str, Any]:
    reset_demo()
    baseline = run_pytest()
    test_digest = digest(TEST_FILE)
    started = monotonic()
    settings = Settings.from_env(workspace=str(DEMO))
    app = create_app(settings)

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        metadata = client.get("/api/meta").json()
        if not metadata.get("agent_ready"):
            raise RuntimeError("Model configuration is incomplete")
        created = client.post("/api/tasks", json={"prompt": PROMPT})
        created.raise_for_status()
        task_id = created.json()["id"]
        stream = client.get(f"/api/tasks/{task_id}/events")
        stream.raise_for_status()
        events = decode_sse(stream.text)
        task = client.get(f"/api/tasks/{task_id}").json()

    elapsed = round(monotonic() - started, 3)
    verification = run_pytest()
    types = [event["type"] for event in events]
    tool_events = [event for event in events if event["type"] == "tool_started"]
    tool_results = [event for event in events if event["type"] == "tool_finished"]
    file_events = [event for event in events if event["type"] == "file_changed"]
    command_events = [event for event in events if event["type"] == "command_finished"]
    summary = task.get("summary") or {}
    verification_summary = summary.get("verification") or {}
    checks = {
        "baseline_failed": baseline.returncode != 0,
        "task_completed": task["status"] == "COMPLETED",
        "terminal_event_completed": bool(events) and types[-1] == "task_completed",
        "implementation_changed": any(
            event["payload"].get("path") == "calculator.py" for event in file_events
        ),
        "tests_unchanged": digest(TEST_FILE) == test_digest,
        "agent_ran_passing_tests": any(
            event["payload"].get("ok") is True
            and "pytest" in str(event["payload"].get("command", ""))
            for event in command_events
        ),
        "independent_tests_passed": verification.returncode == 0,
        "terminal_summary_present": bool(summary),
        "summary_recorded_change": "calculator.py" in summary.get("files_changed", []),
        "summary_verification_passed": verification_summary.get("passed") is True,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "run": number,
        "success": not failures,
        "elapsed_seconds": elapsed,
        "decision_steps": max((event.get("step", 0) for event in events), default=0),
        "tool_calls": len(tool_events),
        "tool_names": [event["payload"].get("tool") for event in tool_events],
        "tool_outcomes": [
            {
                "tool": event["payload"].get("tool"),
                "ok": event["payload"].get("ok"),
                "error_code": event["payload"].get("error_code"),
            }
            for event in tool_results
        ],
        "file_changes": [event["payload"].get("path") for event in file_events],
        "commands": [event["payload"].get("command") for event in command_events],
        "task_status": task["status"],
        "error_code": (task.get("error") or {}).get("code"),
        "checks": checks,
        "failure_reasons": failures,
        "independent_pytest": verification.stdout.strip()[-500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "m4-real-demo.json",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")

    results: list[dict[str, Any]] = []
    try:
        for number in range(1, args.runs + 1):
            print(f"Starting real-model demo run {number}/{args.runs}", flush=True)
            try:
                result = run_once(number)
            except Exception as exc:
                result = {
                    "run": number,
                    "success": False,
                    "failure_reasons": [type(exc).__name__],
                }
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        reset_demo()

    report = {
        "runs": args.runs,
        "successes": sum(result["success"] for result in results),
        "success_rate": sum(result["success"] for result in results) / args.runs,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in ("runs", "successes", "success_rate")}))
    return 0 if report["successes"] == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
