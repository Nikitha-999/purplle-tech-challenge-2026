from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from threading import RLock
from uuid import UUID

from app.models import StoreEvent


class EventStoreUnavailable(RuntimeError):
    pass


class EventStore:
    def __init__(self) -> None:
        self._events: OrderedDict[UUID, StoreEvent] = OrderedDict()
        self._lock = RLock()
        self.available = True

    def assert_available(self) -> None:
        if not self.available:
            raise EventStoreUnavailable("event store unavailable")

    def add_many(self, events: list[StoreEvent]) -> tuple[int, int]:
        self.assert_available()
        accepted = 0
        duplicate = 0
        with self._lock:
            for event in events:
                if event.event_id in self._events:
                    duplicate += 1
                    continue
                self._events[event.event_id] = event
                accepted += 1
        return accepted, duplicate

    def all(self) -> list[StoreEvent]:
        self.assert_available()
        with self._lock:
            return list(self._events.values())

    def by_store(self, store_id: str) -> list[StoreEvent]:
        return [event for event in self.all() if event.store_id == store_id]

    def last_event_by_store(self) -> dict[str, datetime]:
        result: dict[str, datetime] = {}
        for event in self.all():
            if event.store_id not in result or event.timestamp > result[event.store_id]:
                result[event.store_id] = event.timestamp
        return result

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


store = EventStore()
