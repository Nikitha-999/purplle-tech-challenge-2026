from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from app.analytics import compute_funnel, compute_heatmap, compute_metrics, detect_anomalies
from app.models import (
    EventError,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    StoreEvent,
)
from app.pos import configured_transactions
from app.storage import EventStoreUnavailable, store

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("store-intelligence")

app = FastAPI(title="Store Intelligence API", version="1.0.0")


@app.middleware("http")
async def structured_logging(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", str(uuid4()))
    start = time.perf_counter()
    status_code = 500
    path_parts = [part for part in request.url.path.split("/") if part]
    store_id = path_parts[1] if len(path_parts) >= 2 and path_parts[0] == "stores" else "-"
    event_count = None
    if request.url.path == "/events/ingest" and request.method == "POST":
        try:
            body = await request.body()
            parsed_body = json.loads(body or b"{}")
            events = parsed_body.get("events", [])
            event_count = len(events)
            if events and isinstance(events[0], dict):
                store_id = events[0].get("store_id") or store_id
        except (json.JSONDecodeError, AttributeError, TypeError):
            event_count = 0
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            json.dumps(
                {
                    "trace_id": trace_id,
                    "store_id": store_id,
                    "endpoint": request.url.path,
                    "latency_ms": latency_ms,
                    "event_count": event_count,
                    "status_code": status_code,
                }
            )
        )


@app.exception_handler(EventStoreUnavailable)
async def unavailable_handler(_: Request, exc: EventStoreUnavailable):
    return JSONResponse(
        status_code=503,
        content={"error": "STORE_UNAVAILABLE", "message": str(exc), "retryable": True},
    )


@app.get("/", include_in_schema=False)
def root():
    return {"service": "store-intelligence", "docs": "/docs", "dashboard": "/dashboard"}


@app.post("/events/ingest", response_model=IngestResponse)
def ingest(payload: IngestRequest, response: Response) -> IngestResponse:
    accepted_events: list[StoreEvent] = []
    errors: list[EventError] = []

    for index, raw in enumerate(payload.events):
        try:
            accepted_events.append(StoreEvent.model_validate(raw))
        except ValidationError as exc:
            errors.append(
                EventError(
                    index=index,
                    event_id=str(raw.get("event_id")) if isinstance(raw, dict) and raw.get("event_id") else None,
                    error=exc.errors()[0]["msg"],
                )
            )

    accepted, duplicate = store.add_many(accepted_events)
    if errors:
        response.status_code = 207
    return IngestResponse(accepted=accepted, duplicate=duplicate, rejected=len(errors), errors=errors)


@app.get("/stores/{id}/metrics")
def metrics(id: str):
    return compute_metrics(id, store.by_store(id), configured_transactions())


@app.get("/Metrics")
def metrics_alias():
    return compute_metrics("ST1008", store.by_store("ST1008"), configured_transactions())


@app.get("/stores/{id}/funnel")
def funnel(id: str):
    return compute_funnel(id, store.by_store(id), configured_transactions())


@app.get("/stores/{id}/heatmap")
def heatmap(id: str):
    return compute_heatmap(id, store.by_store(id))


@app.get("/stores/{id}/anomalies")
def anomalies(id: str):
    return {"store_id": id, "anomalies": detect_anomalies(store.by_store(id), configured_transactions())}


@app.get("/health", response_model=HealthResponse)
def health():
    last = store.last_event_by_store()
    now = datetime.now(UTC)
    warnings = []
    for store_id, timestamp in last.items():
        if now - timestamp > timedelta(minutes=10):
            warnings.append(
                {
                    "store_id": store_id,
                    "type": "STALE_FEED",
                    "message": "No events received for more than 10 minutes.",
                }
            )
    return HealthResponse(
        status="WARN" if warnings else "OK",
        last_event_timestamp_per_store=last,
        warnings=warnings,
    )


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return """
<!doctype html>
<html>
<head>
  <title>Store Intelligence Dashboard</title>
  <style>
    body { font-family: Inter, system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #17202a; }
    main { max-width: 980px; margin: 32px auto; padding: 0 20px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .card { background: white; border: 1px solid #d9dee7; border-radius: 8px; padding: 16px; }
    .label { color: #637083; font-size: 13px; }
    .value { font-size: 30px; font-weight: 700; margin-top: 8px; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; background: white; }
    th, td { text-align: left; padding: 12px; border-bottom: 1px solid #d9dee7; }
  </style>
</head>
<body>
<main>
  <h1>Store Intelligence</h1>
  <div class="grid">
    <div class="card"><div class="label">Visitors</div><div id="visitors" class="value">0</div></div>
    <div class="card"><div class="label">Conversion</div><div id="conversion" class="value">0%</div></div>
    <div class="card"><div class="label">Queue</div><div id="queue" class="value">0</div></div>
    <div class="card"><div class="label">Abandonment</div><div id="abandon" class="value">0%</div></div>
  </div>
  <table>
    <thead><tr><th>Zone</th><th>Visits</th><th>Avg dwell</th><th>Heat</th></tr></thead>
    <tbody id="heatmap"></tbody>
  </table>
</main>
<script>
async function refresh() {
  const store = "ST1008";
  const metrics = await fetch(`/stores/${store}/metrics`).then(r => r.json());
  const heatmap = await fetch(`/stores/${store}/heatmap`).then(r => r.json());
  document.querySelector("#visitors").textContent = metrics.unique_visitors;
  document.querySelector("#conversion").textContent = Math.round(metrics.conversion_rate * 100) + "%";
  document.querySelector("#queue").textContent = metrics.queue_depth;
  document.querySelector("#abandon").textContent = Math.round(metrics.abandonment_rate * 100) + "%";
  document.querySelector("#heatmap").innerHTML = heatmap.cells.map(c =>
    `<tr><td>${c.zone_id}</td><td>${c.visit_frequency}</td><td>${Math.round(c.avg_dwell_ms / 1000)}s</td><td>${c.heat_score}</td></tr>`
  ).join("");
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
