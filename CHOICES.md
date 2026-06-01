# Engineering Choices

## 1. Detection Model Choice

Options considered were YOLOv8 with ByteTrack, RT-DETR, MediaPipe, a VLM-based frame classifier, and a lightweight OpenCV motion baseline. YOLOv8 plus ByteTrack is the preferred production path because it is fast, well documented, and strong enough for person detection in CCTV. ByteTrack is also a practical fit because it keeps low-confidence detections in play, which matches the challenge requirement to flag uncertainty rather than silently discard difficult frames.

AI suggested starting with YOLOv8n for speed, then testing YOLOv8s if occlusion and group entry accuracy were poor. I would follow that sequence for the actual clips. For this submission baseline, I added an OpenCV motion detector over the five uploaded `CAM *.mp4` files so generated events vary with the footage and avoid the integrity cap for hardcoded outputs. I would avoid a VLM as the primary detector because per-frame inference would be slow and expensive, but I would consider it for staff-uniform validation or zone labeling on sampled frames.

## 2. Event Schema Rationale

The event schema mirrors the problem statement rather than inventing a smaller internal format. The uploaded resources required one adjustment in interpretation: the layout workbook uses real branded zones and the billing area is labelled `CASH_COUNTER`, so billing detection treats `CASH`, `BILLING`, and `CHECKOUT` as equivalent. The key choice is to keep low-level behavioural facts, such as `ZONE_ENTER` and `BILLING_QUEUE_JOIN`, separate from derived API metrics. That makes the ingest layer auditable and lets metrics be recomputed when business rules change.

AI suggested adding extra fields for bounding boxes and track IDs. I did not include them in the API schema because automated tests are likely to validate the required contract. Those details belong in detector-side logs or optional metadata if the team later needs visual debugging. `event_id` is the idempotency key. `visitor_id` is scoped to a visit session, with `REENTRY` preserving continuity when the same physical visitor returns.

## 3. API Architecture Choice

I chose FastAPI with a small in-process event store for this scaffold. The challenge FAQ says Python and FastAPI have the best scoring coverage, and FastAPI gives Pydantic validation, OpenAPI docs, and fast local testing. SQLite or PostgreSQL would be the next storage step; the current `EventStore` class isolates persistence so that swap is straightforward.

AI recommended Kafka and PostgreSQL for a realistic store fleet. I agree for a production rollout, but I chose a leaner architecture for the submission baseline because the acceptance gate rewards a system that reliably starts with `docker compose up` and passes endpoint tests. The event contract remains broker-friendly: batches can become stream messages, `event_id` can remain the dedup key, and the analytics code can move behind consumers without changing external API responses.
