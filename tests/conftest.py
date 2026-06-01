# PROMPT: Build pytest fixtures for a FastAPI event-ingestion challenge that must validate idempotency, staff exclusion, and analytics edge cases.
# CHANGES MADE: Kept fixtures small and deterministic, added store clearing between tests, and reused the same sample payload shape as the challenge schema.

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import store


@pytest.fixture(autouse=True)
def clear_store():
    store.clear()
    store.available = True
    yield
    store.clear()
    store.available = True


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_events():
    path = Path(__file__).resolve().parents[1] / "data" / "sample_events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
