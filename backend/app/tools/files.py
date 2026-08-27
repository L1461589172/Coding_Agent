from pydantic import BaseModel, Field

from app.tools.base import ToolArgs, ToolResult, ToolSpec


class ListFilesArgs(ToolArgs):
    path: str = "."
    max_entries: int = Field(default=200, ge=1, le=1000)


class ReadFileArgs(ToolArgs):
    path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class WriteFileArgs(ToolArgs):
    path: str = Field(min_length=1)
    content: str = Field(max_length=100_000)


class ReplaceInFileArgs(ToolArgs):
    path: str = Field(min_length=1)
    old_text: str = Field(min_length=1, max_length=100_000)
    new_text: str = Field(max_length=100_000)


async def not_implemented(arguments: BaseModel) -> ToolResult:
    return ToolResult(
        ok=False,
        error_code="NOT_IMPLEMENTED",
        error_message="文件工具仅定义了协议，未读取或修改任何文件。",
    )


def file_specs() -> list[ToolSpec]:
    return [
        ToolSpec("list_files", "List workspace entries", ListFilesArgs, not_implemented),
        ToolSpec("read_file", "Read UTF-8 text lines", ReadFileArgs, not_implemented),
        ToolSpec("write_file", "Create or overwrite a text file", WriteFileArgs, not_implemented),
        ToolSpec(
            "replace_in_file",
            "Replace exactly one matching span",
            ReplaceInFileArgs,
            not_implemented,
        ),
    ]
