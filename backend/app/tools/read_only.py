"""Bounded filesystem helpers shared by the three read-only tools.

Path checks and post-open identity checks are defense in depth, not an OS sandbox.
Do not use this against a filesystem being changed by an adversarial process.
"""

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from app.tools.workspace import Workspace, WorkspaceError


@dataclass(frozen=True)
class ReadLimits:
    max_file_bytes: int = 1024 * 1024
    max_output_chars: int = 20_000
    max_read_lines: int = 300
    max_scan_entries: int = 10_000
    max_depth: int = 20
    max_search_files: int = 500
    max_search_bytes: int = 8 * 1024 * 1024
    max_snippet_chars: int = 300
    max_scan_seconds: float = 5

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("All read limits must be positive")


class ReadError(ValueError):
    def __init__(self, code: str, message: str, bytes_read: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.bytes_read = bytes_read


@dataclass
class WalkState:
    scanned_entries: int = 0
    skipped_entries: int = 0
    reasons: set[str] = field(default_factory=set)
    started: float = field(default_factory=monotonic)

    def expired(self, limits: ReadLimits) -> bool:
        if monotonic() - self.started >= limits.max_scan_seconds:
            self.reasons.add("time_limit")
            return True
        return False


def walk_entries(
    workspace: Workspace,
    directory: Path,
    limits: ReadLimits,
    state: WalkState,
) -> Iterator[tuple[Path, str]]:
    """Sorted depth-first traversal; ignored entries still count toward scan limits."""

    def visit(path: Path, depth: int) -> Iterator[tuple[Path, str]]:
        if state.expired(limits):
            return
        children: list[Path] = []
        try:
            checked = workspace.resolve(workspace.relative(path))
            with os.scandir(checked) as entries:
                for entry in entries:
                    if state.expired(limits):
                        break
                    if state.scanned_entries >= limits.max_scan_entries:
                        state.reasons.add("scan_limit")
                        break
                    state.scanned_entries += 1
                    children.append(Path(entry.path))
        except (OSError, WorkspaceError):
            if depth == 0:
                raise
            state.skipped_entries += 1
            state.reasons.add("unreadable_entries")
            return
        for child in sorted(children, key=lambda item: (item.name.casefold(), item.name)):
            if state.expired(limits):
                return
            try:
                safe = workspace.resolve(workspace.relative(child))
                info = safe.lstat()
                if Workspace.is_link(info) or not (
                    stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
                ):
                    raise WorkspaceError("Entry is not an ordinary file or directory")
                kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
            except WorkspaceError:
                state.skipped_entries += 1
                continue
            except OSError:
                state.skipped_entries += 1
                state.reasons.add("unreadable_entries")
                continue
            yield safe, kind
            if kind == "directory":
                if depth + 1 >= limits.max_depth:
                    state.reasons.add("depth_limit")
                elif state.scanned_entries < limits.max_scan_entries:
                    yield from visit(safe, depth + 1)
                else:
                    state.reasons.add("scan_limit")

    yield from visit(directory, 0)


def read_text(workspace: Workspace, relative: str, limits: ReadLimits) -> tuple[str, int]:
    path = workspace.resolve(relative)
    before = path.lstat()
    if stat.S_ISDIR(before.st_mode):
        raise IsADirectoryError()
    if Workspace.is_link(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
        raise WorkspaceError("Only ordinary, unlinked files may be read")
    if before.st_size > limits.max_file_bytes:
        raise ReadError("FILE_TOO_LARGE", "File exceeds the configured byte limit")
    # O_NONBLOCK prevents a swapped-in FIFO from hanging on POSIX; Windows device
    # names are rejected by Workspace. Python has no portable parent-directory lock.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
            raise WorkspaceError("File type changed while opening")
        if not os.path.samestat(before, opened):
            raise WorkspaceError("File changed while opening")
        workspace.resolve(relative)
        # Bounded reads even when a file grows after stat; close fd on every path.
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limits.max_file_bytes + 1)
    finally:
        os.close(fd)
    if len(data) > limits.max_file_bytes:
        raise ReadError("FILE_TOO_LARGE", "File exceeds the configured byte limit", len(data))
    if any(byte < 32 and byte not in (9, 10, 13) for byte in data) or b"\x7f" in data:
        raise ReadError("BINARY_FILE", "Binary/control-byte content is not supported", len(data))
    try:
        return data.decode("utf-8-sig"), len(data)
    except UnicodeDecodeError as exc:
        raise ReadError("UNSUPPORTED_ENCODING", "Only UTF-8 text is supported", len(data)) from exc
