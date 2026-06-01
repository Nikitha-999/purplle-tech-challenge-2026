# PROMPT: Generate tests for anomaly detection, health stale-feed warnings, JSONL replay helpers, and the simple tracker integration boundary.
# CHANGES MADE: Made time-sensitive assertions relative to the synthetic data and checked the tracker preserves nearby identities.

from pathlib import Path

from pipeline.emit import read_jsonl
from pipeline.tracker import SimpleTracker


def test_anomalies_detect_queue_spike(client, sample_events):
    client.post("/events/ingest", json={"events": sample_events})

    response = client.get("/stores/ST1008/anomalies")

    anomaly_types = {item["type"] for item in response.json()["anomalies"]}
    assert "BILLING_QUEUE_SPIKE" in anomaly_types


def test_health_reports_last_event_per_store(client, sample_events):
    client.post("/events/ingest", json={"events": sample_events})

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"OK", "WARN"}
    assert "ST1008" in body["last_event_timestamp_per_store"]


def test_read_jsonl_loads_sample_events():
    path = Path(__file__).resolve().parents[1] / "data" / "sample_events.jsonl"

    events = read_jsonl(path)

    assert len(events) == 10
    assert events[0]["event_type"] == "ENTRY"


def test_simple_tracker_reuses_nearby_track():
    tracker = SimpleTracker(max_distance=20)

    first = tracker.update([(100, 100, 0.9)])
    second = tracker.update([(108, 106, 0.8)])
    third = tracker.update([(200, 200, 0.7)])

    assert first[0].visitor_id == second[0].visitor_id
    assert third[0].visitor_id != first[0].visitor_id
