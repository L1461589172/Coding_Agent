import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, Field

from app.tools.base import ToolArgs, ToolResult, ToolSpec
from app.tools.command_policy import CommandError, child_environment, prepare_command
from app.tools.workspace import Workspace


class RunCommandArgs(ToolArgs):
    command: str = Field(min_length=1, max_length=4000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)


@dataclass(frozen=True)
class CommandLimits:
    max_output_bytes: int = 32_768  # Per stream, retained prefix only.
    max_total_output_bytes: int = 4 * 1024 * 1024  # Stop noisy processes, not only truncate.
    cleanup_seconds: float = 3

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("Command limits must be positive")


class Capture:
    def __init__(self, limits: CommandLimits) -> None:
        self.limits = limits
        self.data = {"stdout": bytearray(), "stderr": bytearray()}
        self.counts = {"stdout": 0, "stderr": 0}
        self.lock = threading.Lock()
        self.overflow = threading.Event()
        self.failed = threading.Event()

    def drain(self, stream, name: str) -> None:
        try:
            while chunk := stream.read(8192):
                with self.lock:
                    self.counts[name] += len(chunk)
                    room = self.limits.max_output_bytes - len(self.data[name])
                    self.data[name].extend(chunk[:room])
                    if sum(self.counts.values()) > self.limits.max_total_output_bytes:
                        self.overflow.set()
        except OSError:
            self.failed.set()
        finally:
            stream.close()

    def output(self) -> dict:
        with self.lock:
            return {
                **{
                    name: bytes(data).decode("utf-8", errors="replace")
                    for name, data in self.data.items()
                },
                **{f"{name}_bytes": count for name, count in self.counts.items()},
                **{
                    f"{name}_truncated": self.counts[name] > len(data)
                    for name, data in self.data.items()
                },
            }


class CommandTool:
    def __init__(self, workspace: Workspace, limits: CommandLimits) -> None:
        self.workspace, self.limits = workspace, limits

    async def run_command(self, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, RunCommandArgs)
        stop = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(self._run, arguments, stop))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            stop.set()
            # Keep ownership until process cleanup completes, even on repeated cancellation.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break  # Cleanup ran in the worker; preserve the caller's cancellation.
            if not worker.cancelled():
                worker.exception()
            raise

    def _run(self, args: RunCommandArgs, stop: threading.Event) -> ToolResult:
        environment = child_environment(self.workspace)
        argv = prepare_command(args.command, self.workspace, environment)
        cwd = self.workspace.resolve(".")
        started = monotonic()
        capture = Capture(self.limits)
        process = None
        job = None
        threads: list[threading.Thread] = []
        reason = "exited"
        cleanup_ok = True
        exit_code = None
        try:
            if os.name == "nt":
                from app.tools.windows_job import WindowsJob

                job = WindowsJob()
            process = subprocess.Popen(
                [sys.executable, "-I", "-u", str(Path(__file__).with_name("command_worker.py"))],
                cwd=cwd,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                bufsize=0,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if job is not None:
                job.assign(process.pid)
            for name in ("stdout", "stderr"):
                thread = threading.Thread(
                    target=capture.drain, args=(getattr(process, name), name), daemon=True
                )
                thread.start()
                threads.append(thread)
            if stop.is_set():
                reason = "cancelled"
            else:
                process.stdin.write(json.dumps(argv, ensure_ascii=True).encode("ascii") + b"\n")
                process.stdin.close()
                while process.poll() is None:
                    if stop.is_set():
                        reason = "cancelled"
                        break
                    if capture.overflow.is_set():
                        reason = "output_limit"
                        break
                    if monotonic() - started >= args.timeout_seconds:
                        reason = "timeout"
                        break
                    stop.wait(0.02)
                exit_code = process.poll()
        except OSError as exc:
            raise CommandError(
                "COMMAND_START_FAILED", "Could not start a supervised command"
            ) from exc
        finally:
            # Also clean descendants after normal parent exit (background processes).
            if process is not None:
                try:
                    if job is not None:
                        job.terminate()
                    elif os.name != "nt":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    if process.poll() is None:
                        process.kill()  # Includes a launcher whose Job assignment failed.
                    process.wait(timeout=self.limits.cleanup_seconds)
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_ok = False
                finally:
                    if process.stdin is not None:
                        process.stdin.close()
            if job is not None:
                job.close()
            deadline = monotonic() + self.limits.cleanup_seconds
            for thread in threads:
                thread.join(max(0, deadline - monotonic()))
                cleanup_ok &= not thread.is_alive()
            # Handles with no reader threads (e.g. Job assignment failure).
            if process is not None and not threads:
                process.stdout.close()
                process.stderr.close()
        output = capture.output()
        if reason == "exited" and capture.overflow.is_set():
            reason = "output_limit"
        if not cleanup_ok or capture.failed.is_set():
            reason = "cleanup_failed"
            cleanup_ok = False
        errors = {
            "timeout": ("COMMAND_TIMEOUT", "Command exceeded its time limit"),
            "output_limit": ("COMMAND_OUTPUT_LIMIT", "Command exceeded its output budget"),
            "cancelled": ("COMMAND_CANCELLED", "Command was cancelled"),
            "cleanup_failed": (
                "COMMAND_CLEANUP_FAILED",
                "Process/pipe cleanup could not be confirmed",
            ),
        }
        code, message = errors.get(reason, (None, None))
        if code is None and exit_code != 0:
            code, message = "COMMAND_FAILED", "Command exited with a non-zero status"
        output.update(
            {
                "cwd": ".",
                "exit_code": exit_code,
                "timed_out": reason == "timeout",
                "termination_reason": reason,
                "cleanup_ok": cleanup_ok,
                "duration_seconds": round(monotonic() - started, 3),
            }
        )
        return ToolResult(
            ok=code is None,
            error_code=code,
            error_message=message,
            output=output,
            truncated=output["stdout_truncated"] or output["stderr_truncated"],
        )


def shell_spec(workspace: Workspace, limits: CommandLimits) -> ToolSpec:
    return ToolSpec(
        "run_command",
        "Run an allowlisted local development command; no shell syntax",
        RunCommandArgs,
        CommandTool(workspace, limits).run_command,
        implemented=True,
    )
