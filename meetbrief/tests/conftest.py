from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
import app.db as db
from app.main import app
from app.config import settings

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "settings", replace(db.settings, database_path=str(tmp_path / "meetbrief-test.sqlite"), retention_days=0))
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client

def sign_in(client, username=None, password=None):
    response = client.post("/api/auth/login", json={
        "username": username or settings.admin_username,
        "password": password or settings.admin_password,
    })
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]

def csrf(token):
    return {"X-CSRF-Token": token}

def make_draft(client, token, transcript=None, title="Launch review"):
    transcript = transcript or (
        "Topic: Release\n"
        "[00:00:02] Jordan: We decided to ship the update on 2026-10-30.\n"
        "[00:01:04] Action item: Owner: Casey Lee, due 2026-10-29. Publish release notes.\n"
        "[00:02:30] Unknown speaker: Will the mobile build be ready too?"
    )
    response = client.post("/api/meetings", data={"title": title, "meeting_date": "2026-10-28", "transcript": transcript}, headers=csrf(token))
    assert response.status_code == 201, response.text
    return response.json()
