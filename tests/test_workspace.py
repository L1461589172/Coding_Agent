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
