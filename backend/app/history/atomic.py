import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.history.errors import HistoryStorageUnavailable


def encoded_json(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(prefix=".history-tmp-", dir=path.parent)
        temporary = Path(name)
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        _fsync_parent(path.parent)
    except OSError as exc:
        # os.replace may have committed even when the platform reports an
        # error. The authoritative target bytes decide whether retrying would
        # be safe; never append a second logical revision blindly.
        try:
            committed = path.read_bytes() == content
        except OSError:
            committed = False
        if not committed:
            raise HistoryStorageUnavailable("History update could not be committed") from exc
        try:
            _fsync_parent(path.parent)
        except OSError as durability_error:
            raise HistoryStorageUnavailable(
                "History update durability could not be confirmed"
            ) from durability_error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, encoded_json(value))


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8"))


def cleanup_temporary_files(root: Path) -> None:
    for candidate in root.rglob(".history-tmp-*"):
        if candidate.is_file() and not candidate.is_symlink():
            candidate.unlink(missing_ok=True)
