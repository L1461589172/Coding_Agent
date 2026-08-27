import asyncio
import json
from collections import Counter
from dataclasses import replace

from pydantic import BaseModel, Field, field_validator

from app.tools.base import ToolArgs, ToolResult, ToolSpec
from app.tools.read_only import ReadError, ReadLimits, WalkState, read_text, walk_entries
from app.tools.workspace import Workspace, WorkspaceError


class SearchTextArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=1000)
    path: str = "."
    max_results: int = Field(default=50, ge=1, le=200)

    @field_validator("query")
    @classmethod
    def single_line(cls, query: str) -> str:
        if "\n" in query or "\r" in query or "\x00" in query:
            raise ValueError("query must be a single-line literal")
        return query


class SearchTool:
    def __init__(self, workspace: Workspace, limits: ReadLimits) -> None:
        self.workspace = workspace
        self.limits = limits

    async def search_text(self, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, SearchTextArgs)
        return await asyncio.to_thread(self._search, arguments)

    def _search(self, args: SearchTextArgs) -> ToolResult:
        root = self.workspace.resolve(args.path)
        # A missing explicit target is an error, not an empty successful search.
        root.stat()
        single_file = root.is_file()
        state = WalkState()
        candidates = (
            iter([(root, "file")])
            if single_file
            else walk_entries(
                self.workspace,
                root,
                self.limits,
                state,
            )
        )
        matches = []
        scanned_files = searched_files = scanned_bytes = used_chars = 0
        skipped: Counter[str] = Counter()
        for path, kind in candidates:
            if kind != "file":
                continue
            if state.expired(self.limits):
                break
            if scanned_files >= self.limits.max_search_files:
                state.reasons.add("file_limit")
                break
            remaining = self.limits.max_search_bytes - scanned_bytes
            if remaining <= 0:
                state.reasons.add("byte_limit")
                break
            scanned_files += 1
            relative = self.workspace.relative(path)
            per_file = replace(
                self.limits, max_file_bytes=min(self.limits.max_file_bytes, remaining)
            )
            try:
                safe = self.workspace.resolve(relative)
                size = safe.stat().st_size
                if size > self.limits.max_file_bytes:
                    raise ReadError("FILE_TOO_LARGE", "File exceeds the configured byte limit")
                if size > remaining:
                    state.reasons.add("byte_limit")
                    break
                text, consumed = read_text(self.workspace, relative, per_file)
                scanned_bytes += consumed
            except ReadError as exc:
                if single_file:
                    raise
                # Invalid/binary files have still consumed bounded I/O.
                scanned_bytes += exc.bytes_read
                skipped[exc.code] += 1
                if exc.code == "FILE_TOO_LARGE" and exc.bytes_read > remaining:
                    state.reasons.add("byte_limit")
                    break
                continue
            except (OSError, WorkspaceError):
                if single_file:
                    raise
                skipped["UNREADABLE_FILE"] += 1
                state.reasons.add("unreadable_files")
                continue
            searched_files += 1
            stop = False
            for number, line in enumerate(text.splitlines(), 1):
                if state.expired(self.limits):
                    stop = True
                    break
                column = line.find(args.query)
                if column < 0:
                    continue
                if len(matches) >= args.max_results:
                    state.reasons.add("max_results")
                    stop = True
                    break
                # Even a small custom snippet budget must include the match start.
                context = min(50, max(0, self.limits.max_snippet_chars - len(args.query)))
                start = max(0, column - context)
                snippet = line[start : start + self.limits.max_snippet_chars]
                row = {
                    "path": relative,
                    "line": number,
                    "column": column + 1,
                    "match_length": len(args.query),
                    "text": snippet,
                    "snippet_start_column": start + 1,
                    "snippet_truncated": start > 0 or start + len(snippet) < len(line),
                }
                cost = len(json.dumps(row, ensure_ascii=False)) + 2
                if used_chars + cost > self.limits.max_output_chars:
                    state.reasons.add("output_limit")
                    stop = True
                    break
                matches.append(row)
                used_chars += cost
            if stop:
                break
        return ToolResult(
            ok=True,
            truncated=bool(state.reasons),
            output={
                "path": self.workspace.relative(root),
                "query": args.query,
                "matches": matches,
                "scanned_files": scanned_files,
                "searched_files": searched_files,
                "scanned_bytes": scanned_bytes,
                "skipped_files": dict(skipped),
                "scanned_entries": state.scanned_entries,
                "skipped_entries": state.skipped_entries,
                "truncation_reasons": sorted(state.reasons),
            },
        )


def search_spec(workspace: Workspace, limits: ReadLimits) -> ToolSpec:
    return ToolSpec(
        "search_text",
        "Case-sensitive literal search; one match per line; no regex",
        SearchTextArgs,
        SearchTool(workspace, limits).search_text,
        implemented=True,
    )
