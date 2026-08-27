import asyncio
import os
from dataclasses import replace

import pytest
from app.tools.read_only import ReadLimits
from app.tools.registry import create_registry
from app.tools.workspace import Workspace


def execute(root, name, args, **limits):
    registry = create_registry(Workspace(root), replace(ReadLimits(), **limits))
    return asyncio.run(registry.execute(name, args))


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "计算.py").write_text("first\nneedle = 1\nlast\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("needle documentation\n", encoding="utf-8")
    for ignored in (".git", "node_modules", ".venv", "dist"):
        (tmp_path / ignored).mkdir()
        (tmp_path / ignored / "secret.txt").write_text("needle secret", encoding="utf-8")
    (tmp_path / ".env").write_text("needle credentials", encoding="utf-8")
    return tmp_path


def test_recursive_list_is_sorted_filtered_and_relative(project):
    result = execute(project, "list_files", {})
    assert result.ok and not result.truncated
    assert result.output["entries"] == [
        {"path": "README.md", "type": "file"},
        {"path": "src", "type": "directory"},
        {"path": "src/计算.py", "type": "file"},
    ]
    assert result.output["skipped_entries"] == 5
    nested = execute(project, "list_files", {"path": "src"})
    assert [row["path"] for row in nested.output["entries"]] == ["src/计算.py"]


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("list_files", {"path": "missing"}, "NOT_FOUND"),
        ("list_files", {"path": "README.md"}, "NOT_DIRECTORY"),
        ("read_file", {"path": "src"}, "NOT_FILE"),
        ("read_file", {"path": "missing"}, "NOT_FOUND"),
        ("search_text", {"query": "x", "path": "missing"}, "NOT_FOUND"),
        ("read_file", {"path": "README.md", "start_line": 3, "end_line": 1}, "INVALID_ARGUMENTS"),
        ("read_file", {"path": "README.md", "start_line": "1"}, "INVALID_ARGUMENTS"),
        ("search_text", {"query": "a\nb"}, "INVALID_ARGUMENTS"),
        ("list_files", {"max_entries": 0}, "INVALID_ARGUMENTS"),
        ("search_text", {"query": ""}, "INVALID_ARGUMENTS"),
    ],
)
def test_structured_errors(project, name, args, code):
    result = execute(project, name, args)
    assert not result.ok and result.error_code == code
    assert str(project) not in result.model_dump_json()


@pytest.mark.parametrize(
    "name,args",
    [
        ("list_files", {}),
        ("read_file", {}),
        ("search_text", {"query": "needle"}),
    ],
)
@pytest.mark.parametrize("path", ["../outside.txt", ".git", ".env", "C:\\secret.txt", "NUL"])
def test_all_read_tools_enforce_workspace(project, name, args, path):
    result = execute(project, name, {**args, "path": path})
    assert not result.ok and result.error_code == "PATH_NOT_ALLOWED"
    assert "needle credentials" not in result.model_dump_json()


def test_read_inclusive_lines_bom_and_eof(tmp_path):
    (tmp_path / "file.txt").write_bytes(b"\xef\xbb\xbffirst\r\nsecond\r\nthird")
    result = execute(tmp_path, "read_file", {"path": "file.txt", "start_line": 2, "end_line": 2})
    assert result.ok and not result.truncated
    assert result.output["content"] == "second\r\n"
    assert result.output["total_lines"] == 3
    assert result.output["end_line"] == 2 and result.output["next_start_line"] == 3
    all_text = execute(tmp_path, "read_file", {"path": "file.txt"})
    assert all_text.output["content"].startswith("first")
    past = execute(tmp_path, "read_file", {"path": "file.txt", "start_line": 10})
    assert past.ok and past.output["content"] == "" and past.output["end_line"] is None
    (tmp_path / "empty").touch()
    assert execute(tmp_path, "read_file", {"path": "empty"}).output["total_lines"] == 0


def test_read_truncation_and_size_limit(tmp_path):
    (tmp_path / "lines").write_bytes(b"a\nb\nc\n")
    result = execute(tmp_path, "read_file", {"path": "lines"}, max_read_lines=2)
    assert result.truncated and result.output["content"] == "a\nb\n"
    assert result.output["truncation_reasons"] == ["line_limit"]
    assert result.output["next_start_line"] == 3
    (tmp_path / "long").write_text("abcdefghij\nnext\n", encoding="utf-8")
    short = execute(tmp_path, "read_file", {"path": "long"}, max_output_chars=5)
    assert short.truncated and short.output["content"] == "abcde"
    assert short.output["last_line_truncated"] and short.output["next_start_line"] == 2
    large = execute(tmp_path, "read_file", {"path": "long"}, max_file_bytes=4)
    assert large.error_code == "FILE_TOO_LARGE"


@pytest.mark.parametrize(
    "data,code",
    [
        (b"hello\x00x", "BINARY_FILE"),
        (b"hello\x1bx", "BINARY_FILE"),
        (b"\xff\xfe", "UNSUPPORTED_ENCODING"),
    ],
)
def test_non_text_file_errors(tmp_path, data, code):
    (tmp_path / "data").write_bytes(data)
    assert execute(tmp_path, "read_file", {"path": "data"}).error_code == code
    assert execute(tmp_path, "search_text", {"path": "data", "query": "hello"}).error_code == code


def test_list_limits(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / name).touch()
    limited = execute(tmp_path, "list_files", {"max_entries": 2})
    assert limited.truncated and len(limited.output["entries"]) == 2
    assert "max_entries" in limited.output["truncation_reasons"]
    exact = execute(tmp_path, "list_files", {"max_entries": 3})
    assert not exact.truncated
    scan = execute(tmp_path, "list_files", {}, max_scan_entries=1)
    assert scan.truncated and scan.output["scanned_entries"] == 1
    output = execute(tmp_path, "list_files", {}, max_output_chars=1)
    assert output.truncated and output.output["entries"] == []
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "inner").touch()
    depth = execute(tmp_path, "list_files", {}, max_depth=1)
    assert "depth_limit" in depth.output["truncation_reasons"]
    assert "nested/inner" not in str(depth.output)


def test_literal_case_sensitive_search_and_scope(project):
    result = execute(project, "search_text", {"query": "needle"})
    assert result.ok and not result.truncated
    assert [(row["path"], row["line"]) for row in result.output["matches"]] == [
        ("README.md", 1),
        ("src/计算.py", 2),
    ]
    restricted = execute(project, "search_text", {"path": "src", "query": "needle"})
    assert len(restricted.output["matches"]) == 1
    (project / "literal.txt").write_text("a.*b a.*b\naxxb\nNEEDLE\n中文文本\n", encoding="utf-8")
    literal = execute(project, "search_text", {"path": "literal.txt", "query": "a.*b"})
    assert len(literal.output["matches"]) == 1
    assert literal.output["matches"][0]["column"] == 1
    assert not execute(project, "search_text", {"path": "literal.txt", "query": "needle"}).output[
        "matches"
    ]
    assert execute(project, "search_text", {"query": "中文"}).output["matches"][0]["line"] == 4


def test_search_limits_and_snippets(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"hit\nhit\nhit\n")
    limited = execute(tmp_path, "search_text", {"query": "hit", "max_results": 2})
    assert limited.truncated and len(limited.output["matches"]) == 2
    assert "max_results" in limited.output["truncation_reasons"]
    exact = execute(tmp_path, "search_text", {"query": "hit", "max_results": 3})
    assert not exact.truncated
    output = execute(tmp_path, "search_text", {"query": "hit"}, max_output_chars=1)
    assert output.truncated and not output.output["matches"]
    (tmp_path / "b.txt").write_text("x" * 100 + "needle" + "y" * 100, encoding="utf-8")
    snippet = execute(tmp_path, "search_text", {"query": "needle"}, max_snippet_chars=70)
    row = snippet.output["matches"][0]
    assert len(row["text"]) == 70 and "needle" in row["text"]
    assert row["column"] == 101 and row["snippet_truncated"]
    files = execute(tmp_path, "search_text", {"query": "hit"}, max_search_files=1)
    assert files.truncated and files.output["scanned_files"] == 1
    budget = execute(tmp_path, "search_text", {"query": "hit"}, max_search_bytes=12)
    assert budget.truncated and "byte_limit" in budget.output["truncation_reasons"]
    assert budget.output["scanned_bytes"] == 12


def test_search_skips_unsupported_files_and_reports_counts(tmp_path):
    (tmp_path / "a").write_bytes(b"hit\x00")
    (tmp_path / "b").write_bytes(b"\xff")
    (tmp_path / "c").write_text("hit" * 100, encoding="utf-8")
    (tmp_path / "d").write_text("hit", encoding="utf-8")
    result = execute(tmp_path, "search_text", {"query": "hit"}, max_file_bytes=20)
    assert result.ok
    assert [row["path"] for row in result.output["matches"]] == ["d"]
    assert result.output["skipped_files"] == {
        "BINARY_FILE": 1,
        "UNSUPPORTED_ENCODING": 1,
        "FILE_TOO_LARGE": 1,
    }
    assert result.output["scanned_bytes"] == 8


def test_links_are_neither_followed_nor_returned(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (target / "secret").write_text("needle", encoding="utf-8")
    try:
        os.symlink(target, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit symlinks")
    listing = execute(root, "list_files", {})
    search = execute(root, "search_text", {"query": "needle"})
    assert listing.output["entries"] == [] and search.output["matches"] == []
    assert execute(root, "read_file", {"path": "link/secret"}).error_code == "PATH_NOT_ALLOWED"


def test_permission_errors_and_event_loop_offload(tmp_path, monkeypatch):
    import threading

    from app.tools.files import FileTools

    loop_thread = threading.get_ident()

    def denied(*args):
        assert threading.get_ident() != loop_thread
        raise PermissionError("sensitive local path")

    monkeypatch.setattr(FileTools, "_read_file", denied)
    result = execute(tmp_path, "read_file", {"path": "some-file"})
    assert result.error_code == "PERMISSION_DENIED"
    assert "sensitive" not in result.model_dump_json()


def test_deadline_is_cooperative_and_reported(tmp_path, monkeypatch):
    from app.tools.read_only import WalkState

    (tmp_path / "a").touch()

    def expired(self, limits):
        self.reasons.add("time_limit")
        return True

    monkeypatch.setattr(WalkState, "expired", expired)
    result = execute(tmp_path, "list_files", {})
    assert result.ok and result.truncated and result.output["entries"] == []
    assert result.output["truncation_reasons"] == ["time_limit"]


def test_registries_are_bound_to_separate_workspaces(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "code.txt").write_bytes(b"first")
    (second / "code.txt").write_bytes(b"second")
    assert execute(first, "read_file", {"path": "code.txt"}).output["content"] == "first"
    assert execute(second, "read_file", {"path": "code.txt"}).output["content"] == "second"


def test_reads_preserve_content(project):
    before = {path: path.read_bytes() for path in project.rglob("*") if path.is_file()}
    assert execute(project, "list_files", {}).ok
    assert execute(project, "read_file", {"path": "README.md"}).ok
    assert execute(project, "search_text", {"query": "needle"}).ok
    assert {path: path.read_bytes() for path in before} == before


def test_replaced_file_is_rejected_after_open(tmp_path, monkeypatch):
    from app.tools import read_only

    victim = tmp_path / "code.txt"
    victim.write_bytes(b"old")
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"do not expose replacement")
    original_open = os.open

    def raced_open(path, flags, *args, **kwargs):
        if path == victim:
            os.replace(replacement, victim)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(read_only.os, "open", raced_open)
    result = execute(tmp_path, "read_file", {"path": "code.txt"})
    assert result.error_code == "PATH_NOT_ALLOWED"
    assert "do not expose replacement" not in result.model_dump_json()


def test_unsupported_files_consume_search_byte_budget(tmp_path):
    (tmp_path / "a").write_bytes(b"\x00" * 8)
    (tmp_path / "b").write_bytes(b"hit")
    result = execute(tmp_path, "search_text", {"query": "hit"}, max_search_bytes=8)
    assert result.truncated and not result.output["matches"]
    assert result.output["scanned_bytes"] == 8
    assert result.output["skipped_files"] == {"BINARY_FILE": 1}


def test_oversized_file_does_not_spend_remaining_search_budget(tmp_path):
    (tmp_path / "a").write_bytes(b"hit")
    (tmp_path / "b").write_bytes(b"x" * 30)
    (tmp_path / "c").write_bytes(b"hit")
    result = execute(
        tmp_path, "search_text", {"query": "hit"}, max_file_bytes=20, max_search_bytes=10
    )
    assert result.ok and not result.truncated
    assert [row["path"] for row in result.output["matches"]] == ["a", "c"]
    assert result.output["scanned_bytes"] == 6
    assert result.output["skipped_files"] == {"FILE_TOO_LARGE": 1}


def test_small_snippet_budget_keeps_match_start(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 100 + b"needle" + b"y" * 100)
    result = execute(tmp_path, "search_text", {"query": "needle"}, max_snippet_chars=3)
    row = result.output["matches"][0]
    assert row["text"] == "nee"
    assert row["snippet_start_column"] == row["column"] == 101
    assert row["snippet_truncated"]
