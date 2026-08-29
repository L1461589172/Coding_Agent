import hashlib
import os
import re
import stat
from pathlib import Path
from uuid import UUID

from app.history.errors import HistoryStorageUnavailable

VERSION_NAME = re.compile(r"^v([1-9][0-9]*)$")


def validated_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise HistoryStorageUnavailable("History identifier is invalid") from exc


def workspace_fingerprint(workspace: Path) -> str:
    canonical = os.path.normcase(str(workspace.resolve(strict=True)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_link_info(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def path_is_link(path: Path) -> bool:
    try:
        return _is_link_info(path.lstat())
    except FileNotFoundError:
        return False


def ensure_real_directory(path: Path, *, boundary: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    root = Path(os.path.abspath(boundary))
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise HistoryStorageUnavailable("History path escaped its storage root") from exc

    def validate() -> None:
        current = absolute
        while True:
            try:
                info = current.lstat()
            except FileNotFoundError:
                pass
            else:
                if _is_link_info(info):
                    raise HistoryStorageUnavailable("History directory boundary cannot be a link")
                if not stat.S_ISDIR(info.st_mode):
                    raise HistoryStorageUnavailable("History directory boundary is not a directory")
            if current == root:
                break
            current = current.parent

    validate()
    absolute.mkdir(parents=True, exist_ok=True, mode=0o700)
    validate()
    return absolute


def ensure_history_root(path: Path, *, application_root: Path | None = None) -> Path:
    if not path.is_absolute():
        raise HistoryStorageUnavailable("History directory override must be absolute")
    absolute = Path(os.path.abspath(path))
    if application_root is not None:
        root = application_root.resolve(strict=True)
        try:
            absolute.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise HistoryStorageUnavailable(
                "Default history directory escaped application root"
            ) from exc

    def reject_links() -> None:
        for candidate in (absolute, *absolute.parents):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if _is_link_info(info):
                raise HistoryStorageUnavailable("History directory boundary cannot be a link")

    reject_links()
    absolute.mkdir(parents=True, exist_ok=True, mode=0o700)
    reject_links()
    info = absolute.lstat()
    if _is_link_info(info) or not stat.S_ISDIR(info.st_mode):
        raise HistoryStorageUnavailable("History directory must be a real directory")
    return absolute.resolve(strict=True)


class HistoryPaths:
    def __init__(self, root: Path, workspace: Path) -> None:
        self.root = root
        self.current = root / "CURRENT"
        self.lock = root / "history.lock"
        self.backups = root / "backups"
        self.quarantine = root / "quarantine"
        self.fingerprint = workspace_fingerprint(workspace)

    def version(self, number: int = 1) -> Path:
        return self.root / f"v{number}"

    def workspace(self, number: int = 1) -> Path:
        return self.version(number) / "workspaces" / self.fingerprint

    def sessions(self, number: int = 1) -> Path:
        return self.workspace(number) / "sessions"

    def session(self, session_id: str, number: int = 1) -> Path:
        return self.sessions(number) / validated_uuid(session_id)

    def task(self, session_id: str, ordinal: int, task_id: str, number: int = 1) -> Path:
        if not 1 <= ordinal <= 100:
            raise HistoryStorageUnavailable("Task ordinal is invalid")
        task_name = f"{ordinal:010d}-{validated_uuid(task_id)}.json"
        return self.session(session_id, number) / "tasks" / task_name
