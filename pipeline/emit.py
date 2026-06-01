from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import httpx


def read_jsonl(path: Path) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def chunks(items: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def post_events(api_url: str, events: list[dict], batch_size: int = 100) -> None:
    with httpx.Client(timeout=15) as client:
        for batch in chunks(events, batch_size):
            response = client.post(f"{api_url.rstrip('/')}/events/ingest", json={"events": batch})
            response.raise_for_status()
