from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EventType(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: int | None = None
    sku_zone: str | None = None
    session_seq: int | None = None


class StoreEvent(BaseModel):
    event_id: UUID
    store_id: str = Field(min_length=1)
    camera_id: str = Field(min_length=1)
    visitor_id: str = Field(min_length=1)
    event_type: EventType
    timestamp: datetime
    zone_id: str | None = None
    dwell_ms: int = Field(ge=0)
    is_staff: bool
    confidence: float = Field(ge=0, le=1)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("zone_id")
    @classmethod
    def zone_required_for_zone_events(cls, zone_id: str | None, info: Any) -> str | None:
        event_type = info.data.get("event_type")
        if event_type in {
            EventType.ZONE_ENTER,
            EventType.ZONE_EXIT,
            EventType.ZONE_DWELL,
            EventType.BILLING_QUEUE_JOIN,
            EventType.BILLING_QUEUE_ABANDON,
        } and not zone_id:
            raise ValueError("zone_id is required for zone and billing events")
        return zone_id


class IngestRequest(BaseModel):
    events: list[dict[str, Any]] = Field(max_length=500)


class EventError(BaseModel):
    index: int
    event_id: str | None = None
    error: str


class IngestResponse(BaseModel):
    accepted: int
    duplicate: int
    rejected: int
    errors: list[EventError]


class MetricResponse(BaseModel):
    store_id: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone_ms: dict[str, float]
    queue_depth: int
    abandonment_rate: float
    generated_at: datetime


class FunnelStage(BaseModel):
    stage: str
    count: int
    dropoff_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]


class HeatmapCell(BaseModel):
    zone_id: str
    visit_frequency: int
    avg_dwell_ms: float
    heat_score: int
    data_confidence: str


class HeatmapResponse(BaseModel):
    store_id: str
    cells: list[HeatmapCell]


class Anomaly(BaseModel):
    type: str
    severity: str
    message: str
    suggested_action: str


class HealthResponse(BaseModel):
    status: str
    last_event_timestamp_per_store: dict[str, datetime]
    warnings: list[dict[str, str]]
