import asyncio
import hashlib
import os
import stat
from dataclasses import replace

import pytest
from app.tools import writes
from app.tools.read_only import ReadLimits
from app.tools.registry import create_registry
from app.tools.workspace import Workspace


def execute(root, tool, args, **limits):
    return asyncio.run(
        create_registry(Workspace(root), replace(ReadLimits(), **limits)).execute(tool, args)
    )


def test_create_overwrite_noop_and_diff(tmp_path):
    args = {"path": "src/中文.txt", "content": "first\nsecond\n"}
    result = execute(tmp_path, "write_file", args)
    assert result.ok and result.output["action"] == "created"
    target = tmp_path / "src" / "中文.txt"
    assert target.read_bytes() == b"first\nsecond\n"
    assert result.output["sha256_before"] is None
    assert result.output["sha256_after"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert "--- /dev/null\n+++ b/src/中文.txt" in result.output["diff"]
    stamp = target.stat().st_mtime_ns
    noop = execute(tmp_path, "write_file", args)
    assert noop.ok and not noop.output["changed"] and noop.output["diff"] == ""
    assert target.stat().st_mtime_ns == stamp
    updated = execute(tmp_path, "write_file", {**args, "content": "first\nchanged\n"})
    assert updated.ok and updated.output["action"] == "updated"
    assert "-second\n+changed\n" in updated.output["diff"]
    assert updated.output["added_lines"] == updated.output["removed_lines"] == 1
    assert not list(tmp_path.rglob(".coding-agent-write-*"))


def test_replace_preserves_bom_crlf_and_no_final_newline(tmp_path):
    target = tmp_path / "code.py"
    target.write_bytes(b"\xef\xbb\xbffirst\r\nsecond\r\nlast")
    result = execute(
        tmp_path, "replace_in_file", {"path": "code.py", "old_text": "second", "new_text": "new"}
    )
    assert result.ok
    assert target.read_bytes() == b"\xef\xbb\xbffirst\r\nnew\r\nlast"
    assert "\\ No newline at end of file" in result.output["diff"]


@pytest.mark.parametrize(
    "text,old,code",
    [
        ("hello", "missing", "TEXT_NOT_FOUND"),
        ("a a", "a", "AMBIGUOUS_MATCH"),
        ("aaa", "aa", "AMBIGUOUS_MATCH"),
    ],
)
def test_replace_rejects_nonunique_without_mutation(tmp_path, text, old, code):
    target = tmp_path / "code"
    target.write_text(text, encoding="utf-8")
    result = execute(
        tmp_path, "replace_in_file", {"path": "code", "old_text": old, "new_text": "X"}
    )
    assert result.error_code == code
    assert target.read_text(encoding="utf-8") == text
    assert not list(tmp_path.glob(".coding-agent-write-*"))


@pytest.mark.parametrize("tool", ["write_file", "replace_in_file"])
@pytest.mark.parametrize("path", ["../outside", ".env", ".git/config", "NUL", "C:/outside", "x:y"])
def test_write_path_guards(tmp_path, tool, path):
    args = {
        "path": path,
        **({"content": "x"} if tool == "write_file" else {"old_text": "x", "new_text": "y"}),
    }
    result = execute(tmp_path, tool, args)
    assert result.error_code == "PATH_NOT_ALLOWED"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("data,code", [(b"\x00", "BINARY_FILE"), (b"\xff", "UNSUPPORTED_ENCODING")])
def test_overwrite_rejects_nontext(tmp_path, data, code):
    (tmp_path / "code").write_bytes(data)
    result = execute(tmp_path, "write_file", {"path": "code", "content": "replace"})
    assert result.error_code == code and (tmp_path / "code").read_bytes() == data


def test_new_content_and_diff_limits(tmp_path):
    too_big = execute(
        tmp_path, "write_file", {"path": "nested/code", "content": "中文"}, max_file_bytes=5
    )
    assert too_big.error_code == "FILE_TOO_LARGE" and not (tmp_path / "nested").exists()
    bad = execute(tmp_path, "write_file", {"path": "code", "content": "x\x00"})
    assert bad.error_code == "BINARY_FILE" and not (tmp_path / "code").exists()
    good = execute(
        tmp_path, "write_file", {"path": "code", "content": "line\n" * 100}, max_output_chars=30
    )
    assert good.ok and good.truncated and len(good.output["diff"]) <= 30
    assert (tmp_path / "code").read_bytes() == b"line\n" * 100


def test_missing_replace_and_directory_errors(tmp_path):
    assert (
        execute(
            tmp_path, "replace_in_file", {"path": "missing", "old_text": "a", "new_text": "b"}
        ).error_code
        == "NOT_FOUND"
    )
    assert execute(tmp_path, "write_file", {"path": ".", "content": "x"}).error_code == "NOT_FILE"


def test_hardlink_write_does_not_change_other_name(tmp_path):
    target = tmp_path / "code"
    target.write_bytes(b"original")
    os.link(target, tmp_path / "alias")
    result = execute(tmp_path, "write_file", {"path": "alias", "content": "new"})
    assert result.error_code == "PATH_NOT_ALLOWED" and target.read_bytes() == b"original"


def test_symlink_parent_does_not_write_outside(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    result = execute(root, "write_file", {"path": "link/new", "content": "x"})
    assert result.error_code == "PATH_NOT_ALLOWED" and not list(outside.iterdir())


def test_failed_commit_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "code"
    target.write_bytes(b"original")

    def denied(*args):
        raise PermissionError("do not expose private path")

    monkeypatch.setattr(writes.os, "replace", denied)
    result = execute(tmp_path, "write_file", {"path": "code", "content": "new"})
    assert result.error_code == "PERMISSION_DENIED"
    assert "private" not in result.model_dump_json()
    assert target.read_bytes() == b"original" and list(tmp_path.iterdir()) == [target]


def test_concurrent_edit_detected_before_commit(tmp_path, monkeypatch):
    target = tmp_path / "code"
    target.write_bytes(b"original")
    original_fsync = writes.os.fsync

    def racing_fsync(fd):
        target.write_bytes(b"external edit")
        original_fsync(fd)

    monkeypatch.setattr(writes.os, "fsync", racing_fsync)
    result = execute(tmp_path, "write_file", {"path": "code", "content": "new"})
    assert result.error_code == "FILE_CHANGED"
    assert target.read_bytes() == b"external edit"
    assert not list(tmp_path.glob(".coding-agent-write-*"))


def test_new_file_race_never_clobbers(tmp_path, monkeypatch):
    original_link = writes.os.link

    def racing_link(source, target):
        target.write_bytes(b"external")
        original_link(source, target)

    monkeypatch.setattr(writes.os, "link", racing_link)
    result = execute(tmp_path, "write_file", {"path": "code", "content": "new"})
    assert result.error_code == "FILE_CHANGED" and (tmp_path / "code").read_bytes() == b"external"


def test_existing_mode_preserved(tmp_path):
    target = tmp_path / "code"
    target.write_bytes(b"old")
    before = stat.S_IMODE(target.stat().st_mode)
    assert execute(tmp_path, "write_file", {"path": "code", "content": "new"}).ok
    assert stat.S_IMODE(target.stat().st_mode) == before


def test_new_directories_rolled_back_after_write_failure(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("temporary write denied")

    monkeypatch.setattr(writes.tempfile, "mkstemp", denied)
    result = execute(tmp_path, "write_file", {"path": "new/inner/code", "content": "hello"})
    assert result.error_code == "PERMISSION_DENIED"
    assert not list(tmp_path.iterdir())


def test_unicode_validation_and_empty_file(tmp_path):
    invalid = execute(tmp_path, "write_file", {"path": "code", "content": "\ud800"})
    assert invalid.error_code == "INVALID_ARGUMENTS" and not list(tmp_path.iterdir())
    empty = execute(tmp_path, "write_file", {"path": "empty", "content": ""})
    assert empty.ok and empty.output["changed"] and (tmp_path / "empty").read_bytes() == b""


def test_replace_noop_and_size_limit(tmp_path):
    (tmp_path / "code").write_bytes(b"abc")
    args = {"path": "code", "old_text": "abc", "new_text": "abc"}
    result = execute(tmp_path, "replace_in_file", args)
    assert result.ok and not result.output["changed"]
    large = execute(tmp_path, "replace_in_file", {**args, "new_text": "123456"}, max_file_bytes=5)
    assert large.error_code == "FILE_TOO_LARGE" and (tmp_path / "code").read_bytes() == b"abc"
