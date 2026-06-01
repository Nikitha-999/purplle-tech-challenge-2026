# PROMPT: Generate tests for POST /events/ingest covering schema validation, partial success, idempotency by event_id, and database unavailable behavior.
# CHANGES MADE: Replaced broad assertions with exact accepted/duplicate/rejected counts and added a 503 degradation case.

from app.storage import store


def test_ingest_accepts_events_and_is_idempotent(client, sample_events):
    first = client.post("/events/ingest", json={"events": sample_events})
    assert first.status_code == 200
    assert first.json()["accepted"] == len(sample_events)
    assert first.json()["duplicate"] == 0

    second = client.post("/events/ingest", json={"events": sample_events})
    assert second.status_code == 200
    assert second.json()["accepted"] == 0
    assert second.json()["duplicate"] == len(sample_events)


def test_ingest_partial_success_for_malformed_event(client, sample_events):
    bad_event = dict(sample_events[0])
    bad_event["confidence"] = 2.0

    response = client.post("/events/ingest", json={"events": [sample_events[0], bad_event]})

    assert response.status_code == 207
    body = response.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert body["errors"][0]["index"] == 1


def test_ingest_returns_503_when_store_unavailable(client, sample_events):
    store.available = False

    response = client.post("/events/ingest", json={"events": [sample_events[0]]})

    assert response.status_code == 503
    assert response.json()["error"] == "STORE_UNAVAILABLE"


def test_store_blr_metrics_acceptance_gate_alias_returns_json(client):
    response = client.get("/stores/STORE_BLR_002/metrics")

    assert response.status_code == 200
    assert response.json()["store_id"] == "STORE_BLR_002"
