import asyncio
import ctypes
import json
import os
import time
from dataclasses import replace

import pytest
from app.tools.command_policy import child_environment, prepare_command
from app.tools.registry import create_registry
from app.tools.shell import CommandLimits
from app.tools.workspace import Workspace


def execute(root, command, timeout=5, **limits):
    tools = create_registry(Workspace(root), command_limits=replace(CommandLimits(), **limits))
    return asyncio.run(
        tools.execute("run_command", {"command": command, "timeout_seconds": timeout})
    )


def test_stdout_stderr_exit_status_and_workspace(tmp_path):
    (tmp_path / "probe.py").write_text(
        "import os, sys, json\nprint(json.dumps({'cwd': os.getcwd(), 'arg': sys.argv[1]}))\n"
        "print('stderr sample', file=sys.stderr)\nsys.exit(7)\n",
        encoding="utf-8",
    )
    result = execute(tmp_path, 'python probe.py "hello world"')
    assert not result.ok and result.error_code == "COMMAND_FAILED", result
    assert result.output["exit_code"] == 7 and result.output["cleanup_ok"]
    output = json.loads(result.output["stdout"])
    assert os.path.samefile(output["cwd"], tmp_path) and output["arg"] == "hello world"
    assert "stderr sample" in result.output["stderr"]


def test_echo_unicode_and_python_version(tmp_path):
    result = execute(tmp_path, 'echo "中文 hello"')
    assert result.ok and result.output["stdout"].strip() == "中文 hello", result
    assert execute(tmp_path, "python --version").ok


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "del file",
        "Remove-Item file",
        "shutdown /s",
        "cmd /c echo x",
        "powershell -Command echo",
        "bash -c echo",
        "python -c 'print(1)'",
        "python -m pip install x",
        "node -e '1'",
        "npm install",
        "npx anything",
        "echo x && echo y",
        "echo x | echo y",
        "echo x > file",
        "echo x; echo y",
        "echo $HOME",
        "echo %PATH%",
        "echo `whoami`",
        "echo x\necho y",
        "   ",
        'echo "',
    ],
)
def test_dangerous_or_unsupported_commands_never_launch(tmp_path, command, monkeypatch):
    from app.tools import shell

    def no_launch(*args, **kwargs):
        pytest.fail("Rejected command launched a process")

    monkeypatch.setattr(shell.subprocess, "Popen", no_launch)
    result = execute(tmp_path, command)
    assert result.error_code == "COMMAND_NOT_ALLOWED"


def test_script_path_guards(tmp_path):
    for command in ("python ../outside.py", "node .env/script.js"):
        assert execute(tmp_path, command).error_code == "PATH_NOT_ALLOWED"


def test_environment_does_not_inherit_secrets_or_injection(tmp_path, monkeypatch):
    monkeypatch.setenv("CODING_AGENT_API_KEY", "fixture-private")
    monkeypatch.setenv("UNRELATED_SECRET", "also-private")
    monkeypatch.setenv("PYTHONPATH", "should-not-inherit")
    monkeypatch.setenv("NODE_OPTIONS", "--eval dangerous")
    (tmp_path / "env.py").write_text(
        "import os, json\nprint(json.dumps(dict(os.environ)))", encoding="utf-8"
    )
    result = execute(tmp_path, "python env.py")
    assert result.ok, result
    environment = json.loads(result.output["stdout"])
    assert (
        not {"CODING_AGENT_API_KEY", "UNRELATED_SECRET", "PYTHONPATH", "NODE_OPTIONS"}
        & environment.keys()
    )


def test_output_prefix_is_bounded_and_both_streams_drained(tmp_path):
    (tmp_path / "output.py").write_text(
        "import os\nos.write(1, b'a' * 100000)\nos.write(2, b'b' * 100000)", encoding="utf-8"
    )
    result = execute(tmp_path, "python output.py", max_output_bytes=100)
    assert result.ok and result.truncated and result.output["cleanup_ok"], result
    assert result.output["stdout"] == "a" * 100 and result.output["stderr"] == "b" * 100
    assert result.output["stdout_bytes"] == result.output["stderr_bytes"] == 100000


def test_noisy_process_stopped_at_total_output_budget(tmp_path):
    (tmp_path / "noise.py").write_text(
        "import os\nwhile True: os.write(1, b'x' * 8192)", encoding="utf-8"
    )
    result = execute(
        tmp_path, "python noise.py", max_output_bytes=100, max_total_output_bytes=16000
    )
    assert result.error_code == "COMMAND_OUTPUT_LIMIT" and result.output["cleanup_ok"], result


def test_timeout_returns_partial_output(tmp_path):
    (tmp_path / "sleep.py").write_text(
        "import time\nprint('started', flush=True)\ntime.sleep(30)", encoding="utf-8"
    )
    started = time.monotonic()
    result = execute(tmp_path, "python sleep.py", timeout=1)
    assert result.error_code == "COMMAND_TIMEOUT" and result.output["timed_out"], result
    assert "started" in result.output["stdout"] and result.output["cleanup_ok"]
    assert time.monotonic() - started < 8


def running(pid):
    if os.name == "nt":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed orphan may briefly remain a zombie until its system parent reaps it.
    from pathlib import Path

    info = Path(f"/proc/{pid}/stat")
    return not info.exists() or info.read_text().split()[2] != "Z"


def tree_script(tmp_path, wait):
    (tmp_path / "child.py").write_text("import time\ntime.sleep(30)", encoding="utf-8")
    (tmp_path / "tree.py").write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "p = subprocess.Popen([sys.executable, 'child.py'])\n"
        "Path('child.pid').write_text(str(p.pid))\n" + ("time.sleep(30)\n" if wait else ""),
        encoding="utf-8",
    )


@pytest.mark.parametrize("wait", [False, True])
def test_descendants_cleaned_on_exit_and_timeout(tmp_path, wait):
    tree_script(tmp_path, wait)
    result = execute(tmp_path, "python tree.py", timeout=2)
    assert result.output["cleanup_ok"], result
    assert result.error_code == ("COMMAND_TIMEOUT" if wait else None)
    pid = int((tmp_path / "child.pid").read_text())
    for _ in range(100):
        if not running(pid):
            break
        time.sleep(0.02)
    assert not running(pid), "Command descendant survived cleanup"


def test_cancellation_waits_for_process_tree_cleanup(tmp_path):
    tree_script(tmp_path, True)

    async def scenario():
        registry = create_registry(Workspace(tmp_path))
        task = asyncio.create_task(registry.execute("run_command", {"command": "python tree.py"}))
        for _ in range(250):
            if (tmp_path / "child.pid").exists():
                break
            await asyncio.sleep(0.02)
        assert (tmp_path / "child.pid").exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not running(int((tmp_path / "child.pid").read_text()))


def test_python_alias_uses_backend_interpreter(tmp_path):
    import sys

    workspace = Workspace(tmp_path)
    args = prepare_command("pytest -q", workspace, child_environment(workspace))
    assert args == [sys.executable, "-m", "pytest", "-q"]


def test_local_tool_workflow_without_llm(tmp_path):
    async def scenario():
        registry = create_registry(Workspace(tmp_path))
        result = await registry.execute(
            "write_file",
            {"path": "test_example.py", "content": "def test_sum():\n    assert 1 + 1 == 3\n"},
        )
        assert result.ok
        # Dedicated temp root avoids the host's account-sharing pytest directory.
        command = "python -m pytest test_example.py -q --basetemp=.tool-pytest-tmp"
        failed = await registry.execute("run_command", {"command": command})
        assert failed.error_code == "COMMAND_FAILED" and failed.output["exit_code"] == 1, failed
        assert (await registry.execute("read_file", {"path": "test_example.py"})).ok
        assert (
            await registry.execute(
                "replace_in_file",
                {"path": "test_example.py", "old_text": "== 3", "new_text": "== 2"},
            )
        ).ok
        passed = await registry.execute("run_command", {"command": command})
        assert passed.ok and "1 passed" in passed.output["stdout"], passed

    asyncio.run(scenario())


def test_start_failure_has_structured_safe_error(tmp_path, monkeypatch):
    from app.tools import shell

    def denied(*args, **kwargs):
        raise PermissionError("private-path")

    monkeypatch.setattr(shell.subprocess, "Popen", denied)
    result = execute(tmp_path, "echo hello")
    assert result.error_code == "COMMAND_START_FAILED"
    assert "private-path" not in result.model_dump_json()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job assignment")
def test_job_assignment_failure_does_not_execute_target(tmp_path, monkeypatch):
    from app.tools.windows_job import WindowsJob

    def denied(*args):
        raise PermissionError("Job assignment refused")

    monkeypatch.setattr(WindowsJob, "assign", denied)
    (tmp_path / "probe.py").write_text(
        "from pathlib import Path\nPath('marker').touch()", encoding="utf-8"
    )
    result = execute(tmp_path, "python probe.py")
    assert result.error_code == "COMMAND_START_FAILED" and not (tmp_path / "marker").exists()


def test_invalid_output_decodes_without_crashing(tmp_path):
    (tmp_path / "binary.py").write_text("import os\nos.write(1, b'\\xff\\xfe')", encoding="utf-8")
    result = execute(tmp_path, "python binary.py")
    assert result.ok and "\ufffd" in result.output["stdout"]


def test_node_and_npm_commands_when_installed(tmp_path):
    import shutil

    if not shutil.which("node") or not shutil.which("npm"):
        pytest.skip("Node/npm are optional executables")
    (tmp_path / "probe.cjs").write_text("console.log('node-ok')", encoding="utf-8")
    assert execute(tmp_path, "node probe.cjs").output["stdout"].strip() == "node-ok"
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"check": "node probe.cjs"}}), encoding="utf-8"
    )
    result = execute(tmp_path, "npm run check", timeout=10)
    assert result.ok and "node-ok" in result.output["stdout"], result
