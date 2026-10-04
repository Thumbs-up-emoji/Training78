"""Milestone 6 JWT + API-key security regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.governance.platform import GovernancePlatform
from app.production_api import create_app

WORKSPACE_ROOT = Path(__file__).parents[1]
API_KEY = "m6-test-api-key"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("MILESTONE5_API_KEY", API_KEY)
    monkeypatch.setenv("MILESTONE5_JWT_SECRET", "m6-test-jwt-secret")
    monkeypatch.setenv("MILESTONE6_DEMO_PASSWORD", "m6-test-password")
    platform = GovernancePlatform(
        workspace_root=WORKSPACE_ROOT,
        database_path=tmp_path / "sales.db",
        memory_path=tmp_path / "memory.db",
        approval_path=tmp_path / "approval.json",
        log_path=tmp_path / "governance.jsonl",
        governance_database_path=tmp_path / "governance.db",
        use_llm=False,
    )
    return TestClient(create_app(platform=platform, span_log_path=tmp_path / "spans.jsonl"))


def _token(client: TestClient) -> str:
    response = client.post(
        "/auth/token",
        headers={"X-API-Key": API_KEY},
        json={"username": "demo-user", "password": "m6-test-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_token_endpoint_still_requires_api_key(client: TestClient) -> None:
    response = client.post("/auth/token", json={"username": "demo-user", "password": "m6-test-password"})
    assert response.status_code == 401


def test_protected_health_requires_jwt_after_api_key(client: TestClient) -> None:
    api_key_only = client.get("/health", headers={"X-API-Key": API_KEY})
    assert api_key_only.status_code == 401

    token = _token(client)
    response = client.get("/health", headers={"X-API-Key": API_KEY, "Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_wrong_demo_credentials_cannot_issue_token(client: TestClient) -> None:
    response = client.post(
        "/auth/token",
        headers={"X-API-Key": API_KEY},
        json={"username": "demo-user", "password": "wrong-password"},
    )
    assert response.status_code == 401