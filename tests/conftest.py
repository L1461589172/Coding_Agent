import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(workspace=tmp_path, api_key="fixture-secret-must-not-leak"))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client
