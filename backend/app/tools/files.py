import asyncio
import json

from pydantic import BaseModel, Field, model_validator

from app.tools.base import ToolArgs, ToolResult, ToolSpec
from app.tools.read_only import ReadLimits, WalkState, read_text, walk_entries
from app.tools.workspace import Workspace
from app.tools.writes import WriteError, commit_text, snapshot


class ListFilesArgs(ToolArgs):
    path: str = "."
    max_entries: int = Field(default=200, ge=1, le=1000)


class ReadFileArgs(ToolArgs):
    path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_range(self) -> "ReadFileArgs":
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class WriteFileArgs(ToolArgs):
    path: str = Field(min_length=1)
    content: str = Field(max_length=100_000)


class ReplaceInFileArgs(ToolArgs):
    path: str = Field(min_length=1)
    old_text: str = Field(min_length=1, max_length=100_000)
    new_text: str = Field(max_length=100_000)


class FileTools:
    def __init__(self, workspace: Workspace, limits: ReadLimits) -> None:
        self.workspace = workspace
        self.limits = limits

    async def write_file(self, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, WriteFileArgs)
        return await self._owned_write(self._write_file, arguments)

    def _write_file(self, args: WriteFileArgs) -> ToolResult:
        with self.workspace.write_lock:
            previous = snapshot(self.workspace, args.path, self.limits)
            return commit_text(self.workspace, args.path, previous, args.content, self.limits)

    async def replace_in_file(self, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, ReplaceInFileArgs)
        return await self._owned_write(self._replace_in_file, arguments)

    @staticmethod
    async def _owned_write(handler, arguments) -> ToolResult:
        """On cancellation, wait until the atomic write either commits or fails."""

        worker = asyncio.create_task(asyncio.to_thread(handler, arguments))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # A thread cannot be cancelled safely. Keep ownership until the operation
            # settles so shutdown never reports completion while a write can still commit.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled():
                worker.exception()
            raise

    def _replace_in_file(self, args: ReplaceInFileArgs) -> ToolResult:
        from app.tools.read_only import decode_text

        with self.workspace.write_lock:
            previous = snapshot(self.workspace, args.path, self.limits)
            if previous.info is None:
                raise FileNotFoundError()
            text = decode_text(previous.data)
            first = text.find(args.old_text)
            if first < 0:
                raise WriteError("TEXT_NOT_FOUND", "Old text does not occur in the file")
            # Include overlapping occurrences: 'aa' in 'aaa' is ambiguous too.
            if text.find(args.old_text, first + 1) >= 0:
                raise WriteError("AMBIGUOUS_MATCH", "Old text must occur exactly once")
            updated = text[:first] + args.new_text + text[first + len(args.old_text) :]
            return commit_text(self.workspace, args.path, previous, updated, self.limits)

    async def list_files(self, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, ListFilesArgs)
        return await asyncio.to_thread(self._list_files, arguments)

    def _list_files(self, args: ListFilesArgs) -> ToolResult:
        directory = self.workspace.resolve(args.path)
        state = WalkState()
        entries = []
        used_chars = 0
        for path, kind in walk_entries(self.workspace, directory, self.limits, state):
            if len(entries) >= args.max_entries:
                state.reasons.add("max_entries")
                break
            row = {"path": self.workspace.relative(path), "type": kind}
            cost = len(json.dumps(row, ensure_ascii=False)) + 2
            if used_chars + cost > self.limits.max_output_chars:
                state.reasons.add("output_limit")
                break
            entries.append(row)
            used_chars += cost
        return ToolResult(
            ok=True,
            truncated=bool(state.reasons),
            output={
                "path": self.workspace.relative(directory),
                "entries": entries,
                "scanned_entries": state.scanned_entries,
                "skipped_entries": state.skipped_entries,
                "truncation_reasons": sorted(state.reasons),
            },
        )

    async def read_file(self, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, ReadFileArgs)
        return await asyncio.to_thread(self._read_file, arguments)

    def _read_file(self, args: ReadFileArgs) -> ToolResult:
        text, size = read_text(self.workspace, args.path, self.limits)
        lines = text.splitlines(keepends=True)
        requested_end = min(args.end_line if args.end_line is not None else len(lines), len(lines))
        selected_end = min(requested_end, args.start_line + self.limits.max_read_lines - 1)
        reasons = []
        if selected_end < requested_end:
            reasons.append("line_limit")
        parts: list[str] = []
        used_chars = 0
        partial_line = False
        for line in lines[args.start_line - 1 : selected_end]:
            remaining = self.limits.max_output_chars - used_chars
            if remaining == 0:
                reasons.append("output_limit")
                break
            parts.append(line[:remaining])
            used_chars += len(parts[-1])
            if len(line) > remaining:
                reasons.append("output_limit")
                partial_line = True
                break
        end = args.start_line + len(parts) - 1 if parts else None
        next_line = end + 1 if end is not None and end < len(lines) else None
        return ToolResult(
            ok=True,
            truncated=bool(reasons),
            output={
                "path": self.workspace.relative(self.workspace.resolve(args.path)),
                "content": "".join(parts),
                "start_line": args.start_line,
                "end_line": end,
                "returned_lines": len(parts),
                "total_lines": len(lines),
                "file_bytes": size,
                "next_start_line": next_line,
                "last_line_truncated": partial_line,
                "truncation_reasons": reasons,
            },
        )


def file_specs(workspace: Workspace, limits: ReadLimits) -> list[ToolSpec]:
    tools = FileTools(workspace, limits)
    return [
        ToolSpec(
            "list_files",
            "Recursively list allowed workspace entries",
            ListFilesArgs,
            tools.list_files,
            implemented=True,
        ),
        ToolSpec(
            "read_file",
            "Read bounded UTF-8 text with 1-based inclusive line ranges",
            ReadFileArgs,
            tools.read_file,
            implemented=True,
        ),
        ToolSpec(
            "write_file",
            "Atomically create or overwrite UTF-8 text and return a diff",
            WriteFileArgs,
            tools.write_file,
            implemented=True,
        ),
        ToolSpec(
            "replace_in_file",
            "Replace exactly one matching span",
            ReplaceInFileArgs,
            tools.replace_in_file,
            implemented=True,
        ),
    ]
