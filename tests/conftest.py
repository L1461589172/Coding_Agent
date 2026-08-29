import shutil
import tempfile
from pathlib import Path

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def history_dir():
    # Keep this path short enough for the deepest v1 history path on Windows
    # hosts that have not enabled Win32 long-path support.
    path = Path(tempfile.mkdtemp(prefix="cah-"))
    yield path.resolve()
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def client(tmp_path, history_dir):
    app = create_app(
        Settings(
            workspace=tmp_path,
            api_key="fixture-secret-must-not-leak",
            history_dir=history_dir,
        )
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client
