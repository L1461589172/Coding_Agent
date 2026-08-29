import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app import __version__
from app.history.atomic import atomic_write_json, atomic_write_text, cleanup_temporary_files
from app.history.errors import HistoryDataInvalid, HistoryFormatUnsupported
from app.history.models import (
    FORMAT_VERSION,
    FormatData,
    FormatEnvelope,
    SessionEnvelope,
    SessionIndexEnvelope,
    TaskEnvelope,
    WorkspaceEnvelope,
)
from app.history.paths import VERSION_NAME, HistoryPaths, path_is_link

_ENVELOPES = {
    "format": FormatEnvelope,
    "workspace": WorkspaceEnvelope,
    "index": SessionIndexEnvelope,
    "session": SessionEnvelope,
    "task": TaskEnvelope,
}


def _format_envelope() -> FormatEnvelope:
    return FormatEnvelope(
        revision=1,
        data=FormatData(created_at=datetime.now(UTC), application_version=__version__),
    )


def _validate_tree(root: Path) -> None:
    format_path = root / "format.json"
    try:
        FormatEnvelope.model_validate_json(format_path.read_text(encoding="utf-8"))
        for path in root.rglob("*.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            kind = raw.get("kind")
            model = _ENVELOPES.get(kind)
            if model is None:
                raise ValueError("unknown history envelope kind")
            model.model_validate(raw)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise HistoryDataInvalid("History format validation failed") from exc


def _validate_format(root: Path) -> None:
    if path_is_link(root) or path_is_link(root / "format.json"):
        raise HistoryDataInvalid("History format boundary cannot be a link")
    try:
        FormatEnvelope.model_validate_json((root / "format.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise HistoryDataInvalid("History format metadata is invalid") from exc


def _initialize_v1(paths: HistoryPaths) -> None:
    existing_versions = [path for path in paths.root.iterdir() if VERSION_NAME.fullmatch(path.name)]
    if existing_versions:
        raise HistoryDataInvalid("History CURRENT is missing while version data exists")
    temporary = paths.root / f".history-version-tmp-{uuid4()}"
    try:
        temporary.mkdir(mode=0o700)
        atomic_write_json(temporary / "format.json", _format_envelope())
        (temporary / "workspaces").mkdir(mode=0o700)
        _validate_tree(temporary)
        target = paths.version(FORMAT_VERSION)
        try:
            os.replace(temporary, target)
        except OSError:
            if not target.is_dir():
                raise
            _validate_tree(target)
        atomic_write_text(paths.current, f"v{FORMAT_VERSION}\n")
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _backup_v0(paths: HistoryPaths, source: Path, limit: int, max_bytes: int) -> Path:
    if path_is_link(source) or path_is_link(paths.backups):
        raise HistoryDataInvalid("History migration boundary cannot be a link")
    paths.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups = sorted(path for path in paths.backups.iterdir() if path.is_dir())
    if len(backups) >= limit:
        raise HistoryDataInvalid("History backup limit reached; migration was not started")
    size = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
    existing_size = sum(
        path.stat().st_size for backup in backups for path in backup.rglob("*") if path.is_file()
    )
    if existing_size + size > max_bytes:
        raise HistoryDataInvalid("History backup exceeds the configured migration limit")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = paths.backups / f"{stamp}-v0"
    shutil.copytree(source, target)
    return target


def _migrate_v0_to_v1(paths: HistoryPaths, backup_limit: int, backup_max_bytes: int) -> None:
    source = paths.version(0)
    if not source.is_dir():
        raise HistoryDataInvalid("History v0 directory is missing")
    _backup_v0(paths, source, backup_limit, backup_max_bytes)
    temporary = paths.root / f".history-version-tmp-{uuid4()}"
    try:
        shutil.copytree(source, temporary)
        for json_path in temporary.rglob("*.json"):
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            if raw.get("format_version") != 0:
                raise HistoryDataInvalid("Synthetic v0 data contains an invalid version")
            raw["format_version"] = FORMAT_VERSION
            if raw.get("kind") == "format":
                raw["data"]["application_version"] = __version__
            atomic_write_json(json_path, raw)
        _validate_tree(temporary)
        target = paths.version(FORMAT_VERSION)
        if target.exists():
            raise HistoryDataInvalid("History v1 target already exists")
        try:
            os.replace(temporary, target)
        except OSError:
            if not target.is_dir():
                raise
            _validate_tree(target)
        atomic_write_text(paths.current, f"v{FORMAT_VERSION}\n")
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def initialize_or_migrate(
    paths: HistoryPaths,
    *,
    backup_limit: int = 3,
    backup_max_bytes: int = 64 * 1024 * 1024,
) -> None:
    cleanup_temporary_files(paths.root)
    for temporary in paths.root.glob(".history-version-tmp-*"):
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
    if path_is_link(paths.current):
        raise HistoryDataInvalid("History CURRENT cannot be a link")
    if not paths.current.exists():
        _initialize_v1(paths)
        return
    try:
        current = paths.current.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HistoryDataInvalid("History CURRENT cannot be read") from exc
    if current == "v0":
        version = 0
    else:
        match = VERSION_NAME.fullmatch(current)
        if match is None:
            raise HistoryDataInvalid("History CURRENT is invalid")
        version = int(match.group(1))
    if version < 0:
        raise HistoryDataInvalid("History CURRENT is invalid")
    if version > FORMAT_VERSION:
        raise HistoryFormatUnsupported("History format is newer than this application")
    if version == 0:
        _migrate_v0_to_v1(paths, backup_limit, backup_max_bytes)
    _validate_format(paths.version(FORMAT_VERSION))
