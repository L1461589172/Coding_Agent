import os

import pytest
from app.tools.workspace import Workspace, WorkspaceError


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "a/../../outside",
        "/etc/passwd",
        "C:\\secret.txt",
        "C:secret.txt",
        "\\\\server\\share",
        ".git/config",
        ".env",
        ".env.local",
        "a/PRIVATE.KEY",
        "node_modules/x",
        "file.txt:stream",
        "\x00",
        "",
        ".git./config",
        ".env ",
        "CON",
        "con.txt",
        "LPT1.log",
        "com¹.txt",
        "con .txt",
        "\\\\?\\C:\\secret",
        "\\\\.\\NUL",
        "name?",
        "name*",
        "name\n.txt",
        "name\x1b.txt",
        "folder/BACKEN~1/file",
        ".aws/credentials",
        ".npmrc",
        "a.p12",
        "dist/main.js",
        "x" * 256,
        "x\ud800",
    ],
)
def test_reject_unsafe_path(tmp_path, path):
    with pytest.raises(WorkspaceError):
        Workspace(tmp_path).resolve(path)


def test_resolve_new_file_and_normalized_separator(tmp_path):
    workspace = Workspace(tmp_path)
    assert workspace.resolve("src/main.py") == tmp_path / "src" / "main.py"
    assert workspace.resolve("src\\main.py") == tmp_path / "src" / "main.py"
    assert workspace.resolve(".") == tmp_path


def test_invalid_workspace(tmp_path):
    with pytest.raises(FileNotFoundError):
        Workspace(tmp_path / "missing")
    file = tmp_path / "file"
    file.touch()
    with pytest.raises(WorkspaceError):
        Workspace(file)


def test_symlink_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit creating symlinks for this test user")
    with pytest.raises(WorkspaceError):
        Workspace(root).resolve("link/new.txt")


def test_internal_and_dangling_symlinks_rejected(tmp_path):
    target = tmp_path / "safe"
    target.mkdir()
    try:
        os.symlink(target, tmp_path / "inside", target_is_directory=True)
        os.symlink(tmp_path / "missing", tmp_path / "dangling", target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit creating symlinks for this test user")
    for path in ("inside/a.txt", "dangling/a.txt"):
        with pytest.raises(WorkspaceError):
            Workspace(tmp_path).resolve(path)


def test_hard_link_rejected(tmp_path):
    original = tmp_path / "original.txt"
    original.write_text("data", encoding="utf-8")
    try:
        os.link(original, tmp_path / "alias.txt")
    except OSError:
        pytest.skip("Hard links not supported")
    with pytest.raises(WorkspaceError):
        Workspace(tmp_path).resolve("alias.txt")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_junction_rejected_without_touching_target(tmp_path):
    import _winapi

    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    marker = target / "secret.txt"
    marker.write_text("do not read", encoding="utf-8")
    junction = root / "junction"
    _winapi.CreateJunction(str(target), str(junction))
    try:
        with pytest.raises(WorkspaceError):
            Workspace(root).resolve("junction/secret.txt")
    finally:
        junction.rmdir()
    assert marker.read_text(encoding="utf-8") == "do not read"


def test_percent_names_not_url_decoded(tmp_path):
    assert Workspace(tmp_path).resolve("..%2Fsecret") == tmp_path / "..%2Fsecret"


def test_replaced_root_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    workspace = Workspace(root)
    root.rename(tmp_path / "old_root")
    root.mkdir()
    with pytest.raises(WorkspaceError):
        workspace.resolve(".")
