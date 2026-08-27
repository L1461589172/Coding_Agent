"""Small argv allowlist, not a sandbox for the programs/scripts it admits."""

import os
import re
import shlex
import shutil
import sys
from pathlib import Path

from app.tools.workspace import Workspace


class CommandError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def child_environment(workspace: Workspace) -> dict[str, str]:
    # Do not inherit API keys, tokens, PYTHONPATH, NODE_OPTIONS, shell hooks, etc.
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "LANG",
        "LC_ALL",
        "PATHEXT",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    if os.name == "nt":
        # npm lifecycle scripts require ComSpec. Pin it instead of inheriting a shell override.
        env["COMSPEC"] = str(Path(os.environ["SYSTEMROOT"]) / "System32" / "cmd.exe")
    search_path = []
    for value in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(value)
        if (
            value
            and directory.is_absolute()
            and not directory.resolve().is_relative_to(workspace.root)
        ):
            search_path.append(str(directory))
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), *search_path])
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "NO_COLOR": "1",
            "CI": "1",
        }
    )
    return env


def executable(name: str, env: dict[str, str], workspace: Workspace) -> str:
    # Iterate absolute PATH entries to avoid Windows' implicit cwd search.
    for directory in env["PATH"].split(os.pathsep):
        candidate = shutil.which(str(Path(directory) / name), path="")
        if candidate and not Path(candidate).resolve().is_relative_to(workspace.root):
            return str(Path(candidate).resolve())
    raise CommandError("COMMAND_NOT_FOUND", "Required executable is not installed on trusted PATH")


def prepare_command(command: str, workspace: Workspace, env: dict[str, str]) -> list[str]:
    if any(ord(char) < 32 or ord(char) == 127 or char in "|&;<>`$%^" for char in command):
        raise CommandError(
            "COMMAND_NOT_ALLOWED", "Shell operators and expansions are not supported"
        )
    try:
        command.encode("utf-8")
        args = shlex.split(command, posix=True)
    except (ValueError, UnicodeError) as exc:
        raise CommandError(
            "COMMAND_NOT_ALLOWED", "Command must use valid quoted argv syntax"
        ) from exc
    if not args:
        raise CommandError("COMMAND_NOT_ALLOWED", "Command must not be blank")
    name, tail = args[0].casefold(), args[1:]
    if name.endswith(".exe"):
        name = name[:-4]
    if name == "echo":
        return [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            "-c",
            "import sys; print(' '.join(sys.argv[1:]))",
            *tail,
        ]
    if name in {"python", "python3"}:
        if tail in (["--version"], ["-V"]):
            return [sys.executable, *tail]
        if len(tail) >= 2 and tail[0] == "-m" and tail[1] in {"pytest", "unittest", "compileall"}:
            return [sys.executable, *tail]
        if tail and not tail[0].startswith("-"):
            script = workspace.resolve(tail[0])
            if script.suffix.casefold() == ".py" and script.is_file():
                return [sys.executable, str(script), *tail[1:]]
    elif name == "pytest":
        return [sys.executable, "-m", "pytest", *tail]
    elif name == "node":
        if tail in (["--version"], ["-v"]):
            return [executable("node", env, workspace), *tail]
        if tail and not tail[0].startswith("-"):
            script = workspace.resolve(tail[0])
            if script.suffix.casefold() in {".js", ".cjs", ".mjs"} and script.is_file():
                return [executable("node", env, workspace), str(script), *tail[1:]]
    elif name == "npm":
        valid = tail in (["--version"], ["-v"], ["test"])
        valid |= len(tail) == 2 and tail[0] == "run" and bool(re.fullmatch(r"[\w:_-]+", tail[1]))
        if valid:
            node = executable("node", env, workspace)
            npm = executable("npm", env, workspace)
            cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
            if os.name != "nt":
                cli = Path(npm).resolve()
            if not cli.is_file():
                raise CommandError("COMMAND_NOT_FOUND", "npm CLI could not be resolved")
            # Do not execute npm.cmd through cmd.exe (implicit batch expansion).
            return [node, str(cli), *tail]
    raise CommandError("COMMAND_NOT_ALLOWED", "Command is outside the local development allowlist")
