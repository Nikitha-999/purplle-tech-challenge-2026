from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from app.models import (
    Anomaly,
    EventType,
    FunnelResponse,
    FunnelStage,
    HeatmapCell,
    HeatmapResponse,
    MetricResponse,
    StoreEvent,
)
from app.pos import Transaction


def customer_events(events: list[StoreEvent]) -> list[StoreEvent]:
    return [event for event in events if not event.is_staff]


def sessions(events: list[StoreEvent]) -> dict[str, list[StoreEvent]]:
    grouped: dict[str, list[StoreEvent]] = defaultdict(list)
    for event in customer_events(events):
        grouped[event.visitor_id].append(event)
    return {visitor: sorted(items, key=lambda item: item.timestamp) for visitor, items in grouped.items()}


def is_billing_zone(zone_id: str | None) -> bool:
    if not zone_id:
        return False
    normalized = zone_id.upper()
    return any(token in normalized for token in ("BILLING", "CASH", "CHECKOUT"))


def converted_visitors(
    events: list[StoreEvent],
    transactions: list[Transaction] | tuple[Transaction, ...] | None = None,
    store_id: str | None = None,
) -> set[str]:
    customer = customer_events(events)
    if transactions:
        billing_events = [event for event in customer if is_billing_zone(event.zone_id)]
        converted: set[str] = set()
        for transaction in transactions:
            if store_id and transaction.store_id != store_id:
                continue
            for event in billing_events:
                lag_seconds = (transaction.timestamp - event.timestamp).total_seconds()
                if 0 <= lag_seconds <= 300:
                    converted.add(event.visitor_id)
        return converted

    converted: set[str] = set()
    abandoned: set[str] = set()
    for event in customer:
        if event.event_type == EventType.BILLING_QUEUE_ABANDON:
            abandoned.add(event.visitor_id)
            continue
        if is_billing_zone(event.zone_id):
            converted.add(event.visitor_id)
    return converted - abandoned


def latest_queue_depth(events: list[StoreEvent]) -> int:
    joins = [
        event
        for event in customer_events(events)
        if event.event_type == EventType.BILLING_QUEUE_JOIN and event.metadata.queue_depth is not None
    ]
    if not joins:
        return 0
    return max(0, joins[-1].metadata.queue_depth or 0)


def compute_metrics(
    store_id: str,
    events: list[StoreEvent],
    transactions: list[Transaction] | tuple[Transaction, ...] | None = None,
) -> MetricResponse:
    customer = customer_events(events)
    visitor_ids = {event.visitor_id for event in customer}
    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    abandons = 0
    billing_sessions: set[str] = set()

    for event in customer:
        if event.event_type == EventType.ZONE_DWELL and event.zone_id:
            dwell_by_zone[event.zone_id].append(event.dwell_ms)
        if is_billing_zone(event.zone_id):
            billing_sessions.add(event.visitor_id)
        if event.event_type == EventType.BILLING_QUEUE_ABANDON:
            abandons += 1

    converted = converted_visitors(events, transactions, store_id)
    unique_visitors = len(visitor_ids)
    conversion_rate = round(len(converted) / unique_visitors, 4) if unique_visitors else 0.0
    abandonment_rate = round(abandons / len(billing_sessions), 4) if billing_sessions else 0.0

    return MetricResponse(
        store_id=store_id,
        unique_visitors=unique_visitors,
        conversion_rate=conversion_rate,
        avg_dwell_per_zone_ms={
            zone: round(sum(values) / len(values), 2) for zone, values in sorted(dwell_by_zone.items())
        },
        queue_depth=latest_queue_depth(events),
        abandonment_rate=abandonment_rate,
        generated_at=datetime.now(UTC),
    )


def compute_funnel(
    store_id: str,
    events: list[StoreEvent],
    transactions: list[Transaction] | tuple[Transaction, ...] | None = None,
) -> FunnelResponse:
    grouped = sessions(events)
    stage_sets = {
        "Entry": set(),
        "Zone Visit": set(),
        "Billing Queue": set(),
        "Purchase": set(),
    }

    for visitor_id, items in grouped.items():
        types = {event.event_type for event in items}
        zones = {event.zone_id or "" for event in items}
        if EventType.ENTRY in types or EventType.REENTRY in types:
            stage_sets["Entry"].add(visitor_id)
        if any(event_type in types for event_type in (EventType.ZONE_ENTER, EventType.ZONE_DWELL)):
            stage_sets["Zone Visit"].add(visitor_id)
        if EventType.BILLING_QUEUE_JOIN in types or any(is_billing_zone(zone) for zone in zones):
            stage_sets["Billing Queue"].add(visitor_id)
        if visitor_id in converted_visitors(items, transactions, store_id):
            stage_sets["Purchase"].add(visitor_id)

    previous = None
    stages: list[FunnelStage] = []
    for name, visitors in stage_sets.items():
        count = len(visitors)
        dropoff = 0.0 if previous in (None, 0) else round((previous - count) / previous * 100, 2)
        stages.append(FunnelStage(stage=name, count=count, dropoff_pct=max(0.0, dropoff)))
        previous = count
    return FunnelResponse(store_id=store_id, stages=stages)


def compute_heatmap(store_id: str, events: list[StoreEvent]) -> HeatmapResponse:
    customer = customer_events(events)
    visits: dict[str, set[str]] = defaultdict(set)
    dwell: dict[str, list[int]] = defaultdict(list)

    for event in customer:
        if not event.zone_id:
            continue
        if event.event_type in {EventType.ZONE_ENTER, EventType.ZONE_DWELL, EventType.BILLING_QUEUE_JOIN}:
            visits[event.zone_id].add(event.visitor_id)
        if event.event_type == EventType.ZONE_DWELL:
            dwell[event.zone_id].append(event.dwell_ms)

    max_visits = max((len(value) for value in visits.values()), default=0)
    session_count = len(sessions(events))
    confidence = "LOW" if session_count < 20 else "HIGH"
    cells = []
    for zone_id in sorted(visits):
        visit_frequency = len(visits[zone_id])
        heat_score = int(round(visit_frequency / max_visits * 100)) if max_visits else 0
        dwell_values = dwell.get(zone_id, [])
        avg_dwell = round(sum(dwell_values) / len(dwell_values), 2) if dwell_values else 0.0
        cells.append(
            HeatmapCell(
                zone_id=zone_id,
                visit_frequency=visit_frequency,
                avg_dwell_ms=avg_dwell,
                heat_score=heat_score,
                data_confidence=confidence,
            )
        )
    return HeatmapResponse(store_id=store_id, cells=cells)


def detect_anomalies(events: list[StoreEvent], transactions: list[Transaction] | tuple[Transaction, ...] | None = None) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    queue_depth = latest_queue_depth(events)
    if queue_depth >= 6:
        anomalies.append(
            Anomaly(
                type="BILLING_QUEUE_SPIKE",
                severity="CRITICAL" if queue_depth >= 10 else "WARN",
                message=f"Billing queue depth is {queue_depth}.",
                suggested_action="Open another billing counter or assign floor staff to queue management.",
            )
        )

    metrics = compute_metrics(events[0].store_id, events, transactions) if events else None
    if metrics and metrics.unique_visitors >= 5 and metrics.conversion_rate < 0.15:
        anomalies.append(
            Anomaly(
                type="CONVERSION_DROP",
                severity="WARN",
                message=f"Conversion rate is {metrics.conversion_rate:.2%}, below operating threshold.",
                suggested_action="Review staffing, billing wait time, and product availability for this window.",
            )
        )

    now = max((event.timestamp for event in events), default=datetime.now(UTC))
    zones = {event.zone_id for event in events if event.zone_id}
    for zone in sorted(zones):
        latest = max(event.timestamp for event in events if event.zone_id == zone)
        if now - latest > timedelta(minutes=30):
            anomalies.append(
                Anomaly(
                    type="DEAD_ZONE",
                    severity="INFO",
                    message=f"No customer activity in {zone} for more than 30 minutes.",
                    suggested_action="Check camera coverage and consider staff-assisted discovery for the zone.",
                )
            )
    return anomalies
