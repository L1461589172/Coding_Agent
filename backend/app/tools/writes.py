"""Auditable text mutations. Atomic replacement is not an adversarial FS sandbox."""

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.tools.base import ToolResult
from app.tools.read_only import ReadError, ReadLimits, decode_text, read_bytes
from app.tools.workspace import Workspace


class WriteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    info: os.stat_result | None


def same_version(before: os.stat_result, after: os.stat_result) -> bool:
    return os.path.samestat(before, after) and (
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)


def snapshot(workspace: Workspace, relative: str, limits: ReadLimits) -> Snapshot:
    path = workspace.resolve(relative)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return Snapshot(b"", None)
    data = read_bytes(workspace, relative, limits)
    after = workspace.resolve(relative).lstat()
    if not same_version(before, after):
        raise WriteError("FILE_CHANGED", "File changed while preparing the edit")
    decode_text(data)  # Never silently overwrite a binary or unsupported-encoding file.
    return Snapshot(data, after)


def unified_diff(before: str, after: str, path: str, created: bool, limit: int) -> dict:
    """Linear-time single-hunk diff, intentionally not a minimal edit algorithm."""
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1
    old_end, new_end = len(old) - suffix, len(new) - suffix
    removed, added = old_end - prefix, new_end - prefix
    if not removed and not added:
        return {"diff": "", "diff_truncated": False, "added_lines": 0, "removed_lines": 0}
    start = max(0, prefix - 3)
    old_stop, new_stop = min(len(old), old_end + 3), min(len(new), new_end + 3)
    parts: list[str] = []
    used = 0
    truncated = False

    def append(value: str) -> None:
        nonlocal used, truncated
        room = limit - used
        parts.append(value[:room])
        used += min(room, len(value))
        truncated |= len(value) > room

    append(f"--- {'/dev/null' if created else 'a/' + path}\n+++ b/{path}\n")
    append(
        f"@@ -{start + 1 if old_stop > start else start},{old_stop - start} "
        f"+{start + 1 if new_stop > start else start},{new_stop - start} @@\n"
    )
    groups = (
        (" ", old[start:prefix]),
        ("-", old[prefix:old_end]),
        ("+", new[prefix:new_end]),
        (" ", new[new_end:new_stop]),
    )
    for marker, lines in groups:
        for line in lines:
            append(marker + line)
            if not line.endswith(("\n", "\r")):
                append("\n\\ No newline at end of file\n")
            if truncated:
                break
        if truncated:
            break
    return {
        "diff": "".join(parts),
        "diff_truncated": truncated,
        "added_lines": added,
        "removed_lines": removed,
    }


def commit_text(
    workspace: Workspace, relative: str, previous: Snapshot, text: str, limits: ReadLimits
) -> ToolResult:
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WriteError("UNSUPPORTED_ENCODING", "Content must be valid UTF-8 text") from exc
    if previous.data.startswith(b"\xef\xbb\xbf") and not data.startswith(b"\xef\xbb\xbf"):
        data = b"\xef\xbb\xbf" + data
    if len(data) > limits.max_file_bytes:
        raise ReadError("FILE_TOO_LARGE", "New content exceeds the configured byte limit")
    new_text = decode_text(data)
    path = workspace.resolve(relative)
    canonical = workspace.relative(path)
    created = previous.info is None
    changed = created or data != previous.data
    diff = unified_diff(
        decode_text(previous.data), new_text, canonical, created, limits.max_output_chars
    )
    pending_cleanup = False
    if changed:
        made_dirs: list[Path] = []
        temporary: Path | None = None
        temp_info = None
        committed = False
        try:
            parent = workspace.root
            for part in path.parent.relative_to(workspace.root).parts:
                parent /= part
                workspace.resolve(workspace.relative(parent))
                try:
                    parent.mkdir()
                    made_dirs.append(parent)
                except FileExistsError:
                    pass
                if not workspace.resolve(workspace.relative(parent)).is_dir():
                    raise NotADirectoryError()
            parent_info = parent.stat()
            fd, temp_name = tempfile.mkstemp(prefix=".coding-agent-write-", dir=parent)
            temporary = Path(temp_name)
            temp_info = temporary.lstat()
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if previous.info is not None:
                os.chmod(temporary, stat.S_IMODE(previous.info.st_mode))
            current = snapshot(workspace, relative, limits)
            if (
                (current.info is None) != created
                or current.data != previous.data
                or (
                    previous.info is not None
                    and current.info is not None
                    and not same_version(previous.info, current.info)
                )
            ):
                raise WriteError("FILE_CHANGED", "File changed before commit; edit not applied")
            checked_parent = workspace.resolve(workspace.relative(parent))
            if not os.path.samestat(parent_info, checked_parent.stat()):
                raise WriteError("FILE_CHANGED", "Parent directory changed before commit")
            if created:
                # Atomic no-clobber publication, including a file appearing after the check.
                try:
                    os.link(temporary, path)
                except FileExistsError as exc:
                    raise WriteError("FILE_CHANGED", "Target appeared before commit") from exc
            else:
                os.replace(temporary, path)
            committed = True
        finally:
            if temporary is not None:
                try:
                    workspace.resolve(workspace.relative(temporary.parent))
                    if temporary.exists() and os.path.samestat(temp_info, temporary.lstat()):
                        temporary.unlink()
                except (OSError, ValueError):
                    # Do not delete an unchecked path after a concurrent parent replacement.
                    pending_cleanup = True
            if not committed:
                for directory in reversed(made_dirs):
                    try:
                        workspace.resolve(workspace.relative(directory)).rmdir()
                    except (OSError, ValueError):
                        pass  # Never recursively remove directories or other actors' content.
    return ToolResult(
        ok=True,
        truncated=diff["diff_truncated"],
        output={
            "path": canonical,
            "action": "created" if created else "updated" if changed else "unchanged",
            "changed": changed,
            "bytes_before": len(previous.data),
            "bytes_after": len(data),
            "sha256_before": hashlib.sha256(previous.data).hexdigest() if not created else None,
            "sha256_after": hashlib.sha256(data).hexdigest(),
            "cleanup_pending": pending_cleanup,
            **diff,
        },
    )
