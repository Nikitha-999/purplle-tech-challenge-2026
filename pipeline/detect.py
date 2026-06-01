from __future__ import annotations

import argparse
import json
import time
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.emit import post_events, read_jsonl


def load_layout(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def camera_id_from_name(layout: dict, filename: str) -> str:
    for camera in layout.get("cameras", []):
        if camera.get("filename") == filename:
            return camera["camera_id"]
    return Path(filename).stem.replace(" ", "_").upper()


def primary_zone_for_camera(layout: dict, camera_id: str) -> str | None:
    for camera in layout.get("cameras", []):
        if camera.get("camera_id") == camera_id:
            coverage = camera.get("coverage", [])
            return coverage[-1] if coverage else None
    return None


def motion_events_from_video(
    video_path: Path,
    layout: dict,
    camera_id: str,
    start_time: datetime,
    max_seconds: int | None = None,
) -> list[dict]:
    try:
        import cv2
    except ImportError as exc:
        raise SystemExit(
            "OpenCV is required for --video/--cctv-zip mode. Install requirements.txt or use Docker."
        ) from exc

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 15
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_every = max(1, int(fps * 10))
    warmup_frames = int(fps * 5)
    subtractor = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=32, detectShadows=True)
    store_id = layout["store_id"]
    zone_id = primary_zone_for_camera(layout, camera_id)
    events: list[dict] = []
    active = False
    visitor_seq = 1

    frame_index = 0
    while True:
        if max_seconds is not None and frame_index / fps > max_seconds:
            break
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index < warmup_frames or frame_index % sample_every != 0:
            if frame_index < warmup_frames:
                subtractor.apply(frame)
            frame_index += 1
            continue

        mask = subtractor.apply(frame)
        mask = cv2.medianBlur(mask, 5)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        moving_area = sum(cv2.contourArea(contour) for contour in contours if cv2.contourArea(contour) > 800)
        timestamp = start_time + timedelta(seconds=frame_index / fps)
        has_activity = moving_area > 12000

        if has_activity and not active:
            visitor_id = f"VIS_{camera_id}_{visitor_seq:05d}"
            visitor_seq += 1
            event_type = "ENTRY" if camera_id == "CAM_1" else "ZONE_ENTER"
            events.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": camera_id,
                    "visitor_id": visitor_id,
                    "event_type": event_type,
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "zone_id": None if event_type == "ENTRY" else zone_id,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": min(0.99, max(0.35, moving_area / max(frame.shape[0] * frame.shape[1], 1))),
                    "metadata": {"queue_depth": None, "sku_zone": zone_id, "session_seq": 1},
                }
            )
            if camera_id == "CAM_3":
                events[-1]["event_type"] = "BILLING_QUEUE_JOIN"
                events[-1]["zone_id"] = layout["billing_zone"]["zone_id"]
                events[-1]["metadata"]["queue_depth"] = min(12, max(1, int(moving_area // 25000)))
            active = True
        elif not has_activity:
            active = False
        frame_index += 1

    capture.release()
    if frame_count == 0 and not events:
        raise SystemExit(f"No readable frames found in {video_path}")
    return events


def events_from_cctv_zip(
    zip_path: Path,
    layout_path: Path,
    output_path: Path | None,
    max_seconds: int | None = None,
) -> list[dict]:
    layout = load_layout(layout_path)
    start_time = datetime.fromisoformat(f"{layout['business_date']}T10:00:00+00:00")
    events: list[dict] = []
    with TemporaryDirectory() as temp_root:
        temp_dir = Path(temp_root)
        with zipfile.ZipFile(zip_path) as archive:
            members = [member for member in archive.namelist() if member.lower().endswith(".mp4")]
            for member in sorted(members):
                filename = Path(member).name
                video_path = temp_dir / filename
                video_path.write_bytes(archive.read(member))
                camera_id = camera_id_from_name(layout, filename)
                events.extend(motion_events_from_video(video_path, layout, camera_id, start_time, max_seconds))
    if output_path:
        with output_path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Run detection pipeline or replay event JSONL.")
    parser.add_argument("--events", type=Path, help="JSONL events to replay into the API.")
    parser.add_argument("--video", type=Path, help="Challenge video clip path for CV processing.")
    parser.add_argument("--cctv-zip", type=Path, help="Challenge CCTV ZIP containing CAM *.mp4 files.")
    parser.add_argument("--layout", type=Path, default=Path("data/store_layout.json"))
    parser.add_argument("--output", type=Path, help="Optional JSONL path for generated events.")
    parser.add_argument("--max-seconds", type=int, help="Optional per-video limit for smoke tests.")
    parser.add_argument("--store-id", default="ST1008")
    parser.add_argument("--camera-id", default="CAM_1")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--realtime", action="store_true", help="Sleep briefly between events to simulate live flow.")
    args = parser.parse_args()

    if args.events:
        events = read_jsonl(args.events)
        if args.realtime:
            for event in events:
                post_events(args.api, [event], batch_size=1)
                time.sleep(0.25)
        else:
            post_events(args.api, events)
        print(f"emitted {len(events)} events to {args.api}")
        return

    if args.cctv_zip:
        events = events_from_cctv_zip(args.cctv_zip, args.layout, args.output, args.max_seconds)
        post_events(args.api, events)
        print(f"generated and emitted {len(events)} events from {args.cctv_zip}")
        return

    if args.video:
        layout = load_layout(args.layout)
        events = motion_events_from_video(args.video, layout, args.camera_id, datetime.now(UTC), args.max_seconds)
        if args.output:
            with args.output.open("w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event) + "\n")
        post_events(args.api, events)
        print(f"generated and emitted {len(events)} events from {args.video}")
        return

    raise SystemExit("Provide --events or --video.")


if __name__ == "__main__":
    main()
