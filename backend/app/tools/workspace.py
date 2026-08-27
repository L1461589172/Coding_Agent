from pathlib import Path, PureWindowsPath


class WorkspaceError(ValueError):
    pass


class Workspace:
    """Path-level guard, NOT an OS sandbox or a concurrent-filesystem guarantee."""

    BLOCKED = {".git", ".env", ".ssh", "node_modules", ".venv", "__pycache__"}

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("Workspace must be an existing directory")

    @classmethod
    def _check_parts(cls, parts: tuple[str, ...]) -> None:
        for part in parts:
            name = part.casefold()
            if (
                name in cls.BLOCKED
                or name.startswith(".env.")
                or name.endswith((".pem", ".key", ".pfx"))
                or name in {"id_rsa", "id_ed25519"}
            ):
                raise WorkspaceError("Sensitive or dependency path is not allowed")

    def resolve(self, relative: str) -> Path:
        if not relative or "\x00" in relative:
            raise WorkspaceError("Path must be a non-empty relative path")
        windows = PureWindowsPath(relative)
        local = Path(relative.replace("\\", "/"))
        if local.is_absolute() or windows.drive or windows.root or ":" in relative:
            raise WorkspaceError("Absolute paths and alternate data streams are not allowed")
        if ".." in local.parts:
            raise WorkspaceError("Parent traversal is not allowed")
        self._check_parts(local.parts)
        # strict=False also resolves existing parents of a not-yet-created file.
        target = (self.root / local).resolve()
        if not target.is_relative_to(self.root):
            raise WorkspaceError("Path escapes the workspace")
        self._check_parts(target.relative_to(self.root).parts)
        return target
