# PROMPT: Create tests for store metrics, funnel, and heatmap endpoints, including staff exclusion and zero-traffic behavior.
# CHANGES MADE: Added explicit funnel stage assertions so session deduplication is checked instead of only endpoint availability.


def test_metrics_exclude_staff_and_compute_conversion(client, sample_events):
    client.post("/events/ingest", json={"events": sample_events})

    response = client.get("/stores/ST1008/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["unique_visitors"] == 2
    assert body["conversion_rate"] == 0.5
    assert body["queue_depth"] == 7
    assert body["avg_dwell_per_zone_ms"]["DERMDOC"] == 30000


def test_empty_store_metrics_are_zero_not_null(client):
    response = client.get("/stores/EMPTY/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["unique_visitors"] == 0
    assert body["conversion_rate"] == 0
    assert body["queue_depth"] == 0


def test_all_staff_clip_does_not_count_customers(client, sample_events):
    staff_only = []
    for event in sample_events[:3]:
        item = dict(event)
        item["event_id"] = item["event_id"][:-1] + str(len(staff_only) + 1)
        item["visitor_id"] = "VIS_STAFF_ONLY"
        item["is_staff"] = True
        staff_only.append(item)

    client.post("/events/ingest", json={"events": staff_only})
    response = client.get("/stores/ST1008/metrics")

    assert response.json()["unique_visitors"] == 0


def test_reentry_does_not_double_count_funnel_visitor(client, sample_events):
    reentry = dict(sample_events[0])
    reentry["event_id"] = "22222222-2222-4222-8222-222222222222"
    reentry["event_type"] = "REENTRY"
    reentry["timestamp"] = "2026-04-10T17:05:00Z"

    client.post("/events/ingest", json={"events": [sample_events[0], reentry]})
    response = client.get("/stores/ST1008/funnel")

    stages = {stage["stage"]: stage for stage in response.json()["stages"]}
    assert stages["Entry"]["count"] == 1


def test_funnel_uses_sessions_not_staff_events(client, sample_events):
    client.post("/events/ingest", json={"events": sample_events})

    response = client.get("/stores/ST1008/funnel")

    stages = {stage["stage"]: stage for stage in response.json()["stages"]}
    assert stages["Entry"]["count"] == 2
    assert stages["Zone Visit"]["count"] == 2
    assert stages["Billing Queue"]["count"] == 2
    assert stages["Purchase"]["count"] == 1


def test_heatmap_marks_low_confidence_when_few_sessions(client, sample_events):
    client.post("/events/ingest", json={"events": sample_events})

    response = client.get("/stores/ST1008/heatmap")

    cells = response.json()["cells"]
    assert {cell["zone_id"] for cell in cells} >= {"DERMDOC", "GOOD_VIBES"}
    assert all(cell["data_confidence"] == "LOW" for cell in cells)
