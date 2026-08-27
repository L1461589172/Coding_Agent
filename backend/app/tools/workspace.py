import os
import re
import stat
from pathlib import Path, PureWindowsPath
from threading import RLock


class WorkspaceError(ValueError):
    code = "PATH_NOT_ALLOWED"


class Workspace:
    """Path-level guard, NOT an OS sandbox or a concurrent-filesystem guarantee."""

    BLOCKED = {
        ".git",
        ".hg",
        ".svn",
        ".env",
        ".ssh",
        ".aws",
        ".azure",
        ".kube",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "credentials.json",
        "secrets.json",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        "dist",
        "build",
        "coverage",
    }
    DEVICE = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])$", re.I)
    SHORT_ALIAS = re.compile(r"~[0-9]+(?:\.|$)")

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("Workspace must be an existing directory")
        self._root_stat = self.root.stat()
        self.write_lock = RLock()

    @staticmethod
    def is_link(info: os.stat_result) -> bool:
        # FILE_ATTRIBUTE_REPARSE_POINT also covers junctions on Python 3.11.
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)

    @classmethod
    def _check_parts(cls, parts: tuple[str, ...]) -> None:
        for part in parts:
            name = part.casefold()
            if (
                len(part) > 255
                or part.endswith((" ", "."))
                or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"|?*' for char in part)
                or cls.DEVICE.fullmatch(part.split(".")[0].rstrip(" "))
                or cls.SHORT_ALIAS.search(part)
            ):
                raise WorkspaceError("Ambiguous or reserved path component is not allowed")
            if (
                name in cls.BLOCKED
                or name.startswith(".coding-agent-write-")
                or name.startswith(".env.")
                or name.endswith((".pem", ".key", ".pfx", ".p12", ".keystore"))
                or name in {"id_rsa", "id_ed25519"}
            ):
                raise WorkspaceError("Sensitive or dependency path is not allowed")

    def resolve(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or len(relative) > 4096:
            raise WorkspaceError("Path must be a non-empty relative path")
        try:
            relative.encode("utf-8")
        except UnicodeError as exc:
            raise WorkspaceError("Path must be valid Unicode") from exc
        windows = PureWindowsPath(relative)
        local = Path(relative.replace("\\", "/"))
        if local.is_absolute() or windows.drive or windows.root or ":" in relative:
            raise WorkspaceError("Absolute paths and alternate data streams are not allowed")
        if ".." in local.parts:
            raise WorkspaceError("Parent traversal is not allowed")
        self._check_parts(local.parts)
        root_info = self.root.lstat()
        if self.is_link(root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise WorkspaceError("Workspace root changed")
        if not os.path.samestat(root_info, self._root_stat):
            raise WorkspaceError("Workspace root changed")
        current = self.root
        for part in local.parts:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                # Resolve may describe a future write target; read tools require existence.
                break
            if self.is_link(info):
                raise WorkspaceError("Links and reparse points are not allowed")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise WorkspaceError("Only regular files and directories are allowed")
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                raise WorkspaceError("Hard-linked files are not allowed")
        target = (self.root / local).resolve()
        if not target.is_relative_to(self.root):
            raise WorkspaceError("Path escapes the workspace")
        self._check_parts(target.relative_to(self.root).parts)
        return target

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()
