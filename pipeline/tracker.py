from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Track:
    track_id: int
    visitor_id: str
    last_center: tuple[float, float]
    confidence: float


class SimpleTracker:
    """Small deterministic tracker used for tests and as a CV integration boundary."""

    def __init__(self, max_distance: float = 80.0) -> None:
        self.max_distance = max_distance
        self._tracks: list[Track] = []
        self._next_id = 1

    def update(self, detections: list[tuple[float, float, float]]) -> list[Track]:
        updated: list[Track] = []
        for x, y, confidence in detections:
            track = self._nearest(x, y)
            if track is None:
                track = Track(self._next_id, f"VIS_{self._next_id:06d}", (x, y), confidence)
                self._next_id += 1
                self._tracks.append(track)
            else:
                track.last_center = (x, y)
                track.confidence = confidence
            updated.append(track)
        return updated

    def _nearest(self, x: float, y: float) -> Track | None:
        best: Track | None = None
        best_distance = self.max_distance
        for track in self._tracks:
            tx, ty = track.last_center
            distance = ((x - tx) ** 2 + (y - ty) ** 2) ** 0.5
            if distance < best_distance:
                best = track
                best_distance = distance
        return best
