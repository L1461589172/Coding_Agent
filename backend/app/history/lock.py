from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from app.history.errors import HistoryLockUnavailable, HistoryStorageUnavailable


class HistoryFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        try:
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._handle = handle
        except OSError as exc:
            try:
                handle.close()
            except (OSError, UnboundLocalError):
                pass
            raise HistoryLockUnavailable("History directory is already in use") from exc

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise HistoryStorageUnavailable("History lock could not be released") from exc
        finally:
            handle.close()

    def __enter__(self) -> HistoryFileLock:
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
