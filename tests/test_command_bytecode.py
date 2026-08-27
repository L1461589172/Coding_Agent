"""D001: real stale caches, fixed mtimes, and no sleeps to cross a clock boundary."""

import asyncio
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from app.tools.command_policy import child_environment
from app.tools.registry import create_registry
from app.tools.workspace import Workspace

FIXED_TIME_NS = 1_700_000_000_123_456_789
PYTEST_ARGS = ["-q", "--basetemp=.pytest-tmp", "-o", "cache_dir=.pytest-state"]


def call(registry, name, **arguments):
    return asyncio.run(registry.execute(name, arguments))


def pycs(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*.pyc")}


@pytest.mark.parametrize("entry", ["pytest", "python -m pytest", "python3 -m pytest"])
@pytest.mark.parametrize("edit_tool", ["write_file", "replace_in_file"])
@pytest.mark.parametrize("target", ["test_example.py", "example.py"])
def test_stale_bytecode_after_same_timestamp_equal_size_edit(tmp_path, entry, edit_tool, target):
    if target == "test_example.py":
        original = "def test_value():\n    assert 2 == 3\n"
    else:
        original = "value = 3\n"
        (tmp_path / "test_example.py").write_text(
            "from example import value\ndef test_value():\n    assert value == 2\n",
            encoding="utf-8",
        )
    source = tmp_path / target
    source.write_bytes(original.encode("utf-8"))
    os.utime(source, ns=(FIXED_TIME_NS, FIXED_TIME_NS))
    original_stat = source.stat()

    # Seed a *real* pre-existing cache, as an ordinary user pytest run would.
    # Explicitly opt out of the tool's cache policy for this fixture setup only.
    env = child_environment(Workspace(tmp_path))
    env.pop("PYTHONPYCACHEPREFIX", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    seeded = subprocess.run(
        [sys.executable, "-m", "pytest", "test_example.py", *PYTEST_ARGS],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert seeded.returncode == 1 and "1 failed" in seeded.stdout, seeded
    cached = pycs(tmp_path)
    target_caches = [
        data for path, data in cached.items() if path.name.startswith(source.stem + ".")
    ]
    assert len(target_caches) == 1, cached.keys()
    assert struct.unpack("<III", target_caches[0][4:16]) == (
        0,
        int(original_stat.st_mtime),
        original_stat.st_size,
    )

    registry = create_registry(Workspace(tmp_path))
    replacement = original.replace("3", "2")
    arguments = (
        {"content": replacement}
        if edit_tool == "write_file"
        else {"old_text": "3", "new_text": "2"}
    )
    edited = call(registry, edit_tool, path=target, **arguments)
    assert edited.ok and edited.output["changed"], edited
    # Force identical timestamps even on slow machines; byte sizes also match.
    os.utime(source, ns=(FIXED_TIME_NS, FIXED_TIME_NS))
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert source.stat().st_size == original_stat.st_size
    assert source.read_text(encoding="utf-8") == replacement

    command = " ".join([entry, "test_example.py", *PYTEST_ARGS])
    for _ in range(2):
        result = call(registry, "run_command", command=command)
        assert result.ok and "1 passed" in result.output["stdout"], result
    # No recursive deletion or mutation of the user's existing bytecode caches.
    assert pycs(tmp_path) == cached


def test_bytecode_policy_is_fresh_inherited_and_cleaned(tmp_path, monkeypatch):
    inherited_cache = tmp_path / "host-cache"
    inherited_cache.mkdir()
    (inherited_cache / "keep.txt").write_text("untouched", encoding="utf-8")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", str(inherited_cache))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "0")
    (tmp_path / "module.py").write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "child.py").write_text(
        "import json, sys, module\nfrom pathlib import Path\n"
        "print(json.dumps({'prefix': sys.pycache_prefix, 'no_write': sys.dont_write_bytecode, "
        "'exists': Path(sys.pycache_prefix).is_dir(), 'value': module.value}))\n",
        encoding="utf-8",
    )
    (tmp_path / "parent.py").write_text(
        "import subprocess, sys\nsubprocess.run([sys.executable, 'child.py'], check=True)\n",
        encoding="utf-8",
    )
    registry = create_registry(Workspace(tmp_path))
    prefixes = set()
    for _ in range(3):
        result = call(registry, "run_command", command="python parent.py")
        assert result.ok, result
        details = json.loads(result.output["stdout"])
        prefix = Path(details["prefix"])
        assert details["no_write"] and details["exists"] and details["value"] == 2
        assert prefix.is_absolute() and not prefix.is_relative_to(tmp_path)
        assert not prefix.exists(), "Per-command cache directory survived cleanup"
        prefixes.add(prefix)
    assert len(prefixes) == 3
    assert not pycs(tmp_path)
    assert (inherited_cache / "keep.txt").read_text(encoding="utf-8") == "untouched"


@pytest.mark.parametrize("mode", ["success", "failure", "timeout", "cancel", "start", "job"])
def test_bytecode_directory_cleaned_for_every_exit(tmp_path, monkeypatch, mode):
    from app.tools import shell

    if mode == "job" and os.name != "nt":
        pytest.skip("Windows Job assignment")
    created = []
    real_directory = shell.TemporaryDirectory

    def track_directory(*args, **kwargs):
        directory = real_directory(*args, **kwargs)
        created.append(Path(directory.name))
        return directory

    monkeypatch.setattr(shell, "TemporaryDirectory", track_directory)
    (tmp_path / "probe.py").write_text(
        "import os, sys, time\nfrom pathlib import Path\n"
        "Path(os.environ['PYTHONPYCACHEPREFIX'], 'owned.txt').write_text('temporary')\n"
        "Path('started').touch()\n"
        + ("time.sleep(30)\n" if mode in {"timeout", "cancel"} else "")
        + ("sys.exit(1)\n" if mode == "failure" else ""),
        encoding="utf-8",
    )

    def denied(*args, **kwargs):
        raise PermissionError("private-cache-path")

    if mode == "start":
        monkeypatch.setattr(shell.subprocess, "Popen", denied)
    elif mode == "job":
        from app.tools.windows_job import WindowsJob

        monkeypatch.setattr(WindowsJob, "assign", denied)

    registry = create_registry(Workspace(tmp_path))
    if mode == "cancel":

        async def cancel():
            task = asyncio.create_task(
                registry.execute("run_command", {"command": "python probe.py"})
            )
            try:
                for _ in range(250):
                    if (tmp_path / "started").exists():
                        break
                    await asyncio.sleep(0.02)
                assert (tmp_path / "started").exists()
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        asyncio.run(cancel())
    else:
        result = call(registry, "run_command", command="python probe.py", timeout_seconds=1)
        expected = {
            "success": None,
            "failure": "COMMAND_FAILED",
            "timeout": "COMMAND_TIMEOUT",
            "start": "COMMAND_START_FAILED",
            "job": "COMMAND_START_FAILED",
        }
        assert result.error_code == expected[mode], result
        if mode in {"start", "job"}:
            assert not (tmp_path / "started").exists()
            assert "private-cache-path" not in result.model_dump_json()
    assert len(created) == 1 and not created[0].exists()


def test_bytecode_directory_creation_failure_is_safe(tmp_path, monkeypatch):
    from app.tools import shell

    def denied(*args, **kwargs):
        raise PermissionError("private-cache-path")

    def no_launch(*args, **kwargs):
        pytest.fail("Cache setup failure launched a process")

    monkeypatch.setattr(shell, "TemporaryDirectory", denied)
    monkeypatch.setattr(shell.subprocess, "Popen", no_launch)
    result = call(create_registry(Workspace(tmp_path)), "run_command", command="echo hello")
    assert result.error_code == "COMMAND_START_FAILED"
    assert "private-cache-path" not in result.model_dump_json()


def test_bytecode_cleanup_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    from app.tools import shell

    real_directory = shell.TemporaryDirectory

    class UnconfirmedCleanup:
        def __init__(self, **kwargs):
            self.directory = real_directory(**kwargs)
            self.name = self.directory.name

        def cleanup(self):
            self.directory.cleanup()
            raise PermissionError("private-cache-path")

    monkeypatch.setattr(shell, "TemporaryDirectory", UnconfirmedCleanup)
    result = call(create_registry(Workspace(tmp_path)), "run_command", command="echo hello")
    assert not result.ok and result.error_code == "COMMAND_CLEANUP_FAILED", result
    assert result.output["exit_code"] == 0 and not result.output["cleanup_ok"]
    assert "private-cache-path" not in result.model_dump_json()


def test_compileall_bytecode_is_redirected_and_cleaned(tmp_path, monkeypatch):
    from app.tools import shell

    real_directory = shell.TemporaryDirectory
    compiled = []
    created = []

    class ObservedCleanup:
        def __init__(self, **kwargs):
            self.directory = real_directory(**kwargs)
            self.name = self.directory.name
            created.append(Path(self.name))

        def cleanup(self):
            compiled.extend(Path(self.name).rglob("*.pyc"))
            self.directory.cleanup()

    monkeypatch.setattr(shell, "TemporaryDirectory", ObservedCleanup)
    (tmp_path / "module.py").write_text("value = 2\n", encoding="utf-8")
    result = call(
        create_registry(Workspace(tmp_path)),
        "run_command",
        command="python -m compileall -q module.py",
    )
    assert result.ok and result.output["cleanup_ok"], result
    # compileall explicitly writes pycs despite PYTHONDONTWRITEBYTECODE.
    assert len(compiled) == 1 and len(created) == 1
    assert not created[0].exists() and not pycs(tmp_path)
